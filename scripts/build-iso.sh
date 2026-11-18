#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PROFILE_DIR="${REPO_ROOT}/iso-profile"
WORK_DIR="${REPO_ROOT}/work"
OUT_DIR="${REPO_ROOT}/out"
ISO_NAME="kite-os-folio9480-x86_64_v3.iso"
SKIP_REPO_SETUP=0
DRY_RUN=0
JSON_OUT=0

usage() {
  cat <<'EOF'
Usage: build-iso.sh [OPTIONS]

Build the KITE_OS x86-64-v3 bootable ISO for HP EliteBook Folio 9480m.

Options:
  --profile <dir>       Path to archiso profile (default: <repo>/iso-profile)
  --work-dir <dir>      Working directory for staging & archiso (default: <repo>/work)
  --out-dir <dir>       Output directory for ISO & SHA-256 (default: <repo>/out)
  --iso-name <file>     Output ISO filename (default: kite-os-folio9480-x86_64_v3.iso)
  --skip-repo-setup     Skip pacman-key / CachyOS keyring & repo setup
  --dry-run             Print planned commands without modifying files or running mkarchiso
  --json                Emit machine-readable JSON output (with --dry-run)
  -h, --help            Show this help message
EOF
}

resolve_path() {
  local p="$1"
  if [[ "$p" = /* || "$p" =~ ^[A-Za-z]:[/\\] ]]; then
    printf '%s' "$p"
  else
    printf '%s/%s' "${REPO_ROOT}" "$p"
  fi
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
    --profile)
      [[ $# -ge 2 ]] || { echo "Missing value for --profile" >&2; exit 2; }
      PROFILE_DIR="$(resolve_path "$2")"
      shift 2
      ;;
    --work-dir)
      [[ $# -ge 2 ]] || { echo "Missing value for --work-dir" >&2; exit 2; }
      WORK_DIR="$(resolve_path "$2")"
      shift 2
      ;;
    --out-dir)
      [[ $# -ge 2 ]] || { echo "Missing value for --out-dir" >&2; exit 2; }
      OUT_DIR="$(resolve_path "$2")"
      shift 2
      ;;
    --iso-name)
      [[ $# -ge 2 ]] || { echo "Missing value for --iso-name" >&2; exit 2; }
      ISO_NAME="$2"
      shift 2
      ;;
    --skip-repo-setup)
      SKIP_REPO_SETUP=1
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

STAGED_PROFILE="${WORK_DIR}/profile"
ARCHISO_WORK="${WORK_DIR}/archiso"
STAGE_SRC_DEST="${STAGED_PROFILE}/airootfs/opt/kite-os-src"
ISO_PATH="${OUT_DIR}/${ISO_NAME}"
SHA_PATH="${ISO_PATH}.sha256"
CACHYOS_KEY="F3B607488DB35A47"

CANDIDATE_MODULES=(kite-hw-tune kite-shell kite-bridge installer)
STAGED_MODULES=()
ABSENT_MODULES=()
for mod in "${CANDIDATE_MODULES[@]}"; do
  if [[ -d "${REPO_ROOT}/${mod}" ]]; then
    STAGED_MODULES+=("$mod")
  else
    ABSENT_MODULES+=("$mod")
  fi
done

SYSTEMD_WANTS=(
  "NetworkManager.service:/usr/lib/systemd/system/NetworkManager.service"
  "bluetooth.service:/usr/lib/systemd/system/bluetooth.service"
  "thermald.service:/usr/lib/systemd/system/thermald.service"
  "kite-hw-tune.service:/etc/systemd/system/kite-hw-tune.service"
  "kite-power.service:/etc/systemd/system/kite-power.service"
  "kite-firstboot-stage.service:/etc/systemd/system/kite-firstboot-stage.service"
)

if [[ "${DRY_RUN}" -eq 1 ]]; then
  if [[ "${JSON_OUT}" -eq 1 ]]; then
    staged_json=""
    for m in "${STAGED_MODULES[@]}"; do
      [[ -n "$staged_json" ]] && staged_json+=","
      staged_json+="\"$(json_escape "$m")\""
    done
    absent_json=""
    for m in "${ABSENT_MODULES[@]}"; do
      [[ -n "$absent_json" ]] && absent_json+=","
      absent_json+="\"$(json_escape "$m")\""
    done
    wants_json=""
    for w in "${SYSTEMD_WANTS[@]}"; do
      [[ -n "$wants_json" ]] && wants_json+=","
      wants_json+="\"$(json_escape "${w%%:*}")\""
    done

    printf '{'
    printf '"dry_run":true,'
    printf '"repo_root":"%s",' "$(json_escape "${REPO_ROOT}")"
    printf '"profile_dir":"%s",' "$(json_escape "${PROFILE_DIR}")"
    printf '"work_dir":"%s",' "$(json_escape "${WORK_DIR}")"
    printf '"staged_profile":"%s",' "$(json_escape "${STAGED_PROFILE}")"
    printf '"archiso_work":"%s",' "$(json_escape "${ARCHISO_WORK}")"
    printf '"stage_dest":"%s",' "$(json_escape "${STAGE_SRC_DEST}/")"
    printf '"out_dir":"%s",' "$(json_escape "${OUT_DIR}")"
    printf '"iso_path":"%s",' "$(json_escape "${ISO_PATH}")"
    printf '"sha256_path":"%s",' "$(json_escape "${SHA_PATH}")"
    printf '"skip_repo_setup":%s,' "$([[ $SKIP_REPO_SETUP -eq 1 ]] && echo true || echo false)"
    printf '"cachyos_key":"%s",' "${CACHYOS_KEY}"
    printf '"staged_modules":[%s],' "${staged_json}"
    printf '"absent_modules":[%s],' "${absent_json}"
    printf '"systemd_wants":[%s],' "${wants_json}"
    printf '"command":["mkarchiso","-v","-w","%s","-o","%s","%s"]' \
      "$(json_escape "${ARCHISO_WORK}")" \
      "$(json_escape "${OUT_DIR}")" \
      "$(json_escape "${STAGED_PROFILE}")"
    printf '}\n'
  else
    echo "[dry-run] Repo root      : ${REPO_ROOT}"
    echo "[dry-run] Profile dir    : ${PROFILE_DIR}"
    echo "[dry-run] Staged profile : ${STAGED_PROFILE}"
    echo "[dry-run] Stage dest     : ${STAGE_SRC_DEST}/"
    echo "[dry-run] Staged modules : ${STAGED_MODULES[*]:-(none)}"
    echo "[dry-run] Target ISO     : ${ISO_PATH}"
    echo "[dry-run] Target SHA-256 : ${SHA_PATH}"
    if [[ "${SKIP_REPO_SETUP}" -eq 0 ]]; then
      echo "[dry-run] Repo setup     : pacman-key --init && pacman-key --populate archlinux && import CachyOS key ${CACHYOS_KEY} + [cachyos-v3]/[cachyos-core-v3]/[cachyos-extra-v3]"
    fi
    echo "[dry-run] Symlinks       : create multi-user.target.wants/*.service on Linux build FS"
    echo "[dry-run] Command        : mkarchiso -v -w \"${ARCHISO_WORK}\" -o \"${OUT_DIR}\" \"${STAGED_PROFILE}\""
    echo "[dry-run] Checksum       : (cd \"${OUT_DIR}\" && sha256sum \"${ISO_NAME}\" > \"${ISO_NAME}.sha256\")"
  fi
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Error: mkarchiso requires root privileges (run via sudo, WSL2 root, or Docker --privileged)." >&2
  exit 1
fi

if ! command -v mkarchiso >/dev/null 2>&1; then
  echo "Error: 'mkarchiso' not found. Install it with: pacman -S --needed archiso" >&2
  exit 1
fi

if [[ ! -d "${PROFILE_DIR}" ]]; then
  echo "Error: iso-profile directory not found at ${PROFILE_DIR}" >&2
  exit 1
fi

setup_cachyos_repos() {
  echo "[kite-build] Configuring Arch/CachyOS x86-64-v3 keyrings and repositories..."
  if [[ ! -d /etc/pacman.d/gnupg ]]; then
    pacman-key --init
  fi
  pacman-key --populate archlinux

  if ! pacman-key --list-keys "${CACHYOS_KEY}" >/dev/null 2>&1; then
    pacman-key --recv-keys "${CACHYOS_KEY}" --keyserver keyserver.ubuntu.com
    pacman-key --lsign-key "${CACHYOS_KEY}"
  fi

  if [[ ! -f /etc/pacman.d/cachyos-v3-mirrorlist ]]; then
    cp -f "${PROFILE_DIR}/airootfs/etc/pacman.d/cachyos-v3-mirrorlist" /etc/pacman.d/cachyos-v3-mirrorlist
  fi
  if [[ ! -f /etc/pacman.d/cachyos-mirrorlist ]]; then
    cp -f "${PROFILE_DIR}/airootfs/etc/pacman.d/cachyos-mirrorlist" /etc/pacman.d/cachyos-mirrorlist
  fi

  if ! grep -q '^\[cachyos-v3\]' /etc/pacman.conf; then
    cp -f "${PROFILE_DIR}/pacman.conf" /etc/pacman.conf
  fi

  pacman -Sy --noconfirm
  pacman -S --needed --noconfirm cachyos-keyring cachyos-mirrorlist cachyos-v3-mirrorlist || true
}

if [[ "${SKIP_REPO_SETUP}" -eq 0 ]]; then
  setup_cachyos_repos
fi

echo "[kite-build] Preparing staged profile in ${STAGED_PROFILE}..."
rm -rf "${ARCHISO_WORK}" "${STAGED_PROFILE}"
mkdir -p "${STAGE_SRC_DEST}" "${OUT_DIR}"
cp -a "${PROFILE_DIR}/." "${STAGED_PROFILE}/"

for mod in "${STAGED_MODULES[@]}"; do
  echo "[kite-build] Staging ${mod} -> /opt/kite-os-src/${mod}/"
  mkdir -p "${STAGE_SRC_DEST}/${mod}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='node_modules' \
      "${REPO_ROOT}/${mod}/" "${STAGE_SRC_DEST}/${mod}/"
  else
    cp -a "${REPO_ROOT}/${mod}/." "${STAGE_SRC_DEST}/${mod}/"
    find "${STAGE_SRC_DEST}/${mod}" -type d \( -name '.git' -o -name '__pycache__' -o -name '.pytest_cache' -o -name 'node_modules' \) -prune -exec rm -rf {} +
  fi
done

for doc in AGENTS.md README.md; do
  if [[ -f "${REPO_ROOT}/${doc}" ]]; then
    cp -f "${REPO_ROOT}/${doc}" "${STAGE_SRC_DEST}/${doc}"
  fi
done

if [[ -d "${REPO_ROOT}/kite-hw-tune/systemd" ]]; then
  mkdir -p "${STAGED_PROFILE}/airootfs/etc/systemd/system"
  for unit_file in "${REPO_ROOT}/kite-hw-tune/systemd/"*.service; do
    if [[ -f "${unit_file}" ]]; then
      install -m 0644 "${unit_file}" "${STAGED_PROFILE}/airootfs/etc/systemd/system/$(basename "${unit_file}")"
    fi
  done
fi

# Declaratively create systemd multi-user.target.wants symlinks on Linux FS (Windows NTFS symlink safety)
WANTS_DIR="${STAGED_PROFILE}/airootfs/etc/systemd/system/multi-user.target.wants"
mkdir -p "${WANTS_DIR}"
for entry in "${SYSTEMD_WANTS[@]}"; do
  unit="${entry%%:*}"
  target="${entry#*:}"
  if [[ "${target}" == /etc/systemd/system/* && ! -f "${STAGED_PROFILE}/airootfs${target}" ]]; then
    echo "[kite-build] Skipping symlink for ${unit}: unit file ${target} not present in staged airootfs"
    continue
  fi
  ln -sfn "${target}" "${WANTS_DIR}/${unit}"
done

echo "[kite-build] Invoking mkarchiso..."
mkarchiso -v -w "${ARCHISO_WORK}" -o "${OUT_DIR}" "${STAGED_PROFILE}"

GENERATED_ISO="$(find "${OUT_DIR}" -maxdepth 1 -type f -name '*.iso' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
if [[ -z "${GENERATED_ISO}" || ! -f "${GENERATED_ISO}" ]]; then
  echo "Error: mkarchiso finished but no .iso artifact was found in ${OUT_DIR}" >&2
  exit 1
fi

if [[ "$(basename "${GENERATED_ISO}")" != "${ISO_NAME}" ]]; then
  mv -f "${GENERATED_ISO}" "${ISO_PATH}"
fi

(
  cd "${OUT_DIR}"
  sha256sum "${ISO_NAME}" > "${ISO_NAME}.sha256"
)

echo "[kite-build] Success: ${ISO_PATH}"
echo "[kite-build] SHA-256: ${SHA_PATH}"
