#!/usr/bin/env bash
set -euo pipefail

export MESA_LOADER_DRIVER_OVERRIDE="crocus"
export LIBVA_DRIVER_NAME="i965"

KITEBRIDGE_DATA_DIR="${KITEBRIDGE_DATA_DIR:-/var/lib/kitebridge}"
PREFIX="${KITEBRIDGE_DATA_DIR}/macos"
DRY_RUN=0
CHECK_ONLY=0
WITH_OSX_KVM=1
OPENCORE_URL="https://github.com/thenickdude/KVM-Opencore/releases/download/v21/OpenCore-v21.iso.gz"

usage() {
  cat <<'EOF'
Usage: provision-macos.sh [OPTIONS]
  --prefix <dir>      Target macOS state directory (default: /var/lib/kitebridge/macos)
  --check             Verify host binaries, /dev/kvm, and OSX-KVM assets
  --dry-run           Print actions without downloading or creating disk images
  --with-osx-kvm      Include OSX-KVM Haswell assets (default)
  --without-osx-kvm   Provision Tier 1 mount & Darling directories only
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; }
      PREFIX="$2"
      shift 2
      ;;
    --check)
      CHECK_ONLY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --with-osx-kvm)
      WITH_OSX_KVM=1
      shift
      ;;
    --without-osx-kvm)
      WITH_OSX_KVM=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

check_host_tools() {
  local missing=0
  for tool in darling darling-dmg fsck.hfsplus apfs-fuse xar qemu-system-x86_64 virtiofsd qemu-img; do
    if command -v "$tool" >/dev/null 2>&1; then
      printf '[OK] tool: %s\n' "$tool"
    else
      printf '[MISSING] tool: %s\n' "$tool" >&2
      missing=1
    fi
  done

  if [[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]]; then
    printf '[OK] /dev/kvm readable and writable.\n'
  else
    printf '[WARN] /dev/kvm missing or lacks R/W permission (enable VT-x in Folio 9480m BIOS and `usermod -aG kvm $USER`).\n' >&2
    missing=1
  fi
  return "$missing"
}

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  check_host_tools
  exit $?
fi

# Verify @kitebridge Btrfs layout if mounted
if [[ "$DRY_RUN" -eq 0 ]] && command -v findmnt >/dev/null 2>&1; then
  findmnt -n -o FSTYPE,OPTIONS "$KITEBRIDGE_DATA_DIR" 2>/dev/null || true
fi

for sub in osx-kvm images mounts snapshots darling/prefix run cache; do
  run_cmd mkdir -p "${PREFIX}/${sub}"
done

if [[ "$WITH_OSX_KVM" -eq 1 ]]; then
  KVM_DIR="${PREFIX}/osx-kvm"
  OVMF_CODE_SRC="/usr/share/edk2/x64/OVMF_CODE.4m.fd"
  OVMF_VARS_SRC="/usr/share/edk2/x64/OVMF_VARS.4m.fd"
  if [[ ! -f "$OVMF_CODE_SRC" ]]; then
    OVMF_CODE_SRC="/usr/share/edk2/x64/OVMF_CODE.fd"
    OVMF_VARS_SRC="/usr/share/edk2/x64/OVMF_VARS.fd"
  fi

  if [[ -f "$OVMF_CODE_SRC" ]]; then
    run_cmd cp -f "$OVMF_CODE_SRC" "${KVM_DIR}/OVMF_CODE.fd"
  fi
  if [[ -f "$OVMF_VARS_SRC" && ! -f "${KVM_DIR}/OVMF_VARS.fd" ]]; then
    run_cmd cp -f "$OVMF_VARS_SRC" "${KVM_DIR}/OVMF_VARS.fd"
  fi

  if [[ ! -f "${KVM_DIR}/macOS.qcow2" ]]; then
    if command -v qemu-img >/dev/null 2>&1; then
      run_cmd qemu-img create -f qcow2 "${KVM_DIR}/macOS.qcow2" 64G
    else
      printf '[dry-run/skip] qemu-img not present; skipping macOS.qcow2 creation.\n'
    fi
  fi

  if [[ ! -f "${KVM_DIR}/OpenCore.qcow2" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      printf '[dry-run] fetch %s -> convert to %s/OpenCore.qcow2\n' "$OPENCORE_URL" "$KVM_DIR"
    else
      printf 'Fetch OpenCore.qcow2 from %s and macOS recovery via OSX-KVM fetch-macOS-v2.py on first GUI launch.\n' "$OPENCORE_URL"
    fi
  fi
fi

# Note: 16G hosts can enable on-demand hugepages via /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
printf 'macOS subsystem provisioning complete (prefix=%s, CPU invariant: -cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel).\n' "$PREFIX"
