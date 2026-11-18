#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

RAM="8G"
ROTATIONAL="0"
ISO_PATH="${REPO_ROOT}/out/kite-os-folio9480-x86_64_v3.iso"
DISK_PATH="${REPO_ROOT}/work/qemu/kite-os-test.qcow2"
OVMF_CODE=""
OVMF_VARS=""
ACCEL="auto"
HEADLESS=0
DRY_RUN=0
JSON_OUT=0

usage() {
  cat <<'EOF'
Usage: test-qemu.sh [OPTIONS]

Boot or dry-run the HP EliteBook Folio 9480m QEMU Haswell test profile.

Options:
  --ram <4G|8G|16G>         RAM tier to emulate (default: 8G)
  --rotational <0|1>        Storage type: 0 = SSD/mSATA, 1 = HDD (default: 0)
  --iso <path>              Path to KITE_OS ISO (default: out/kite-os-folio9480-x86_64_v3.iso)
  --disk <ssd|hdd|path>     Storage preset (ssd or hdd) or path to qcow2 test disk (default: work/qemu/kite-os-test.qcow2)
  --ovmf-code <path>        Path to OVMF_CODE firmware fd
  --ovmf-vars <path>        Path to OVMF_VARS template fd
  --accel <auto|kvm|whpx|tcg>  QEMU accelerator (default: auto)
  --headless                Run with -display none -serial mon:stdio
  --dry-run                 Print QEMU command without launching
  --json                    Emit JSON payload (with --dry-run)
  -h, --help                Show help
EOF
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ram)
      [[ $# -ge 2 ]] || { echo "Missing value for --ram" >&2; exit 2; }
      RAM="$2"
      shift 2
      ;;
    --rotational)
      [[ $# -ge 2 ]] || { echo "Missing value for --rotational" >&2; exit 2; }
      ROTATIONAL="$2"
      shift 2
      ;;
    --iso)
      [[ $# -ge 2 ]] || { echo "Missing value for --iso" >&2; exit 2; }
      ISO_PATH="$2"
      shift 2
      ;;
    --disk)
      [[ $# -ge 2 ]] || { echo "Missing value for --disk" >&2; exit 2; }
      case "${2,,}" in
        ssd)
          ROTATIONAL="0"
          ;;
        hdd)
          ROTATIONAL="1"
          ;;
        *)
          DISK_PATH="$2"
          ;;
      esac
      shift 2
      ;;
    --ovmf-code)
      [[ $# -ge 2 ]] || { echo "Missing value for --ovmf-code" >&2; exit 2; }
      OVMF_CODE="$2"
      shift 2
      ;;
    --ovmf-vars)
      [[ $# -ge 2 ]] || { echo "Missing value for --ovmf-vars" >&2; exit 2; }
      OVMF_VARS="$2"
      shift 2
      ;;
    --accel)
      [[ $# -ge 2 ]] || { echo "Missing value for --accel" >&2; exit 2; }
      ACCEL="$2"
      shift 2
      ;;
    --headless)
      HEADLESS=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --json)
      JSON_OUT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "${RAM}" in
  4G|8G|16G) ;;
  *)
    echo "Error: Invalid --ram '${RAM}'. Must be one of: 4G, 8G, 16G" >&2
    exit 2
    ;;
esac

case "${ROTATIONAL}" in
  0|1) ;;
  *)
    echo "Error: Invalid --rotational '${ROTATIONAL}'. Must be 0 (SSD) or 1 (HDD)" >&2
    exit 2
    ;;
esac

case "${ACCEL}" in
  auto|kvm|whpx|tcg) ;;
  *)
    echo "Error: Invalid --accel '${ACCEL}'. Must be auto, kvm, whpx, or tcg" >&2
    exit 2
    ;;
esac

if [[ "${ACCEL}" == "auto" ]]; then
  if [[ -r /dev/kvm && -w /dev/kvm ]]; then
    ACCEL="kvm"
  else
    ACCEL="tcg"
  fi
fi

if [[ -z "${OVMF_CODE}" ]]; then
  for candidate in \
    /usr/share/edk2/x64/OVMF_CODE.4m.fd \
    /usr/share/edk2/x64/OVMF_CODE.fd \
    /usr/share/edk2-ovmf/x64/OVMF_CODE.4m.fd \
    /usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
    /usr/share/OVMF/OVMF_CODE_4M.fd \
    /usr/share/OVMF/OVMF_CODE.fd; do
    if [[ -f "${candidate}" ]]; then
      OVMF_CODE="${candidate}"
      break
    fi
  done
  if [[ -z "${OVMF_CODE}" ]]; then
    OVMF_CODE="/usr/share/edk2/x64/OVMF_CODE.4m.fd"
  fi
fi

if [[ -z "${OVMF_VARS}" ]]; then
  for candidate in \
    /usr/share/edk2/x64/OVMF_VARS.4m.fd \
    /usr/share/edk2/x64/OVMF_VARS.fd \
    /usr/share/edk2-ovmf/x64/OVMF_VARS.4m.fd \
    /usr/share/edk2-ovmf/x64/OVMF_VARS.fd \
    /usr/share/OVMF/OVMF_VARS_4M.fd \
    /usr/share/OVMF/OVMF_VARS.fd; do
    if [[ -f "${candidate}" ]]; then
      OVMF_VARS="${candidate}"
      break
    fi
  done
  if [[ -z "${OVMF_VARS}" ]]; then
    OVMF_VARS="/usr/share/edk2/x64/OVMF_VARS.4m.fd"
  fi
fi

QEMU_WORK_DIR="$(dirname "${DISK_PATH}")"
WRITABLE_OVMF_VARS="${QEMU_WORK_DIR}/OVMF_VARS.fd"

if [[ "${ROTATIONAL}" == "0" ]]; then
  ROTATION_RATE="1"
else
  ROTATION_RATE="5400"
fi

QEMU_BIN="qemu-system-x86_64"
QEMU_ARGV=(
  "-name" "KITE_OS-Folio9480m-${RAM}"
  "-machine" "q35"
  "-accel" "${ACCEL}"
  "-cpu" "Haswell-noTSX"
  "-smp" "4,cores=2,threads=2"
  "-m" "${RAM}"
  "-drive" "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}"
  "-drive" "if=pflash,format=raw,file=${WRITABLE_OVMF_VARS}"
  "-device" "virtio-scsi-pci,id=scsi0"
  "-drive" "id=hd0,if=none,format=qcow2,file=${DISK_PATH}"
  "-device" "scsi-hd,drive=hd0,bus=scsi0.0,rotation_rate=${ROTATION_RATE}"
  "-drive" "id=cd0,if=none,media=cdrom,readonly=on,file=${ISO_PATH}"
  "-device" "scsi-cd,drive=cd0,bus=scsi0.0,bootindex=1"
  "-netdev" "user,id=net0"
  "-device" "e1000e,netdev=net0"
  "-device" "intel-hda"
  "-device" "hda-duplex"
)

if [[ "${HEADLESS}" -eq 1 ]]; then
  QEMU_ARGV+=("-display" "none" "-serial" "mon:stdio")
else
  QEMU_ARGV+=("-vga" "std")
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  if [[ "${JSON_OUT}" -eq 1 ]]; then
    argv_json=""
    cmd_str="${QEMU_BIN}"
    for arg in "${QEMU_ARGV[@]}"; do
      [[ -n "$argv_json" ]] && argv_json+=","
      argv_json+="\"$(json_escape "$arg")\""
      cmd_str+=" ${arg}"
    done
    printf '{'
    printf '"dry_run":true,'
    printf '"binary":"%s",' "${QEMU_BIN}"
    printf '"ram":"%s",' "${RAM}"
    printf '"rotational":%s,' "${ROTATIONAL}"
    printf '"rotation_rate":%s,' "${ROTATION_RATE}"
    printf '"accel":"%s",' "${ACCEL}"
    printf '"headless":%s,' "$([[ $HEADLESS -eq 1 ]] && echo true || echo false)"
    printf '"iso":"%s",' "$(json_escape "${ISO_PATH}")"
    printf '"disk":"%s",' "$(json_escape "${DISK_PATH}")"
    printf '"ovmf_code":"%s",' "$(json_escape "${OVMF_CODE}")"
    printf '"ovmf_vars":"%s",' "$(json_escape "${WRITABLE_OVMF_VARS}")"
    printf '"argv":[%s],' "${argv_json}"
    printf '"command":"%s"' "$(json_escape "${cmd_str}")"
    printf '}\n'
  else
    echo "[dry-run] QEMU binary   : ${QEMU_BIN}"
    echo "[dry-run] Folio Profile : -cpu Haswell-noTSX, -smp 4,cores=2,threads=2, -m ${RAM}, rotational=${ROTATIONAL} (rotation_rate=${ROTATION_RATE}), accel=${ACCEL}"
    echo "[dry-run] Command       : ${QEMU_BIN} ${QEMU_ARGV[*]}"
  fi
  exit 0
fi

if ! command -v "${QEMU_BIN}" >/dev/null 2>&1; then
  echo "Error: '${QEMU_BIN}' not found in PATH. Install qemu-system-x86 / qemu-desktop." >&2
  exit 1
fi

if [[ ! -f "${ISO_PATH}" ]]; then
  echo "Error: ISO file not found at ${ISO_PATH}. Run scripts/build-iso.sh first." >&2
  exit 1
fi

if [[ ! -f "${OVMF_CODE}" ]]; then
  echo "Error: OVMF_CODE firmware not found at ${OVMF_CODE}. Install edk2-ovmf." >&2
  exit 1
fi

mkdir -p "${QEMU_WORK_DIR}"
if [[ ! -f "${WRITABLE_OVMF_VARS}" ]]; then
  if [[ ! -f "${OVMF_VARS}" ]]; then
    echo "Error: OVMF_VARS template not found at ${OVMF_VARS}." >&2
    exit 1
  fi
  cp -f "${OVMF_VARS}" "${WRITABLE_OVMF_VARS}"
fi

if [[ ! -f "${DISK_PATH}" ]]; then
  qemu-img create -f qcow2 "${DISK_PATH}" 32G
fi

exec "${QEMU_BIN}" "${QEMU_ARGV[@]}"
