#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${KITE_OS_TARGET_ROOT:-/}"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[kite-ai] dry-run: would install kite_ai package, .kiteignore, kite-aid.socket, kite-index.timer into ${TARGET_ROOT}"
  exit 0
fi

SITE_DIR="${TARGET_ROOT%/}/usr/lib/python3.12/site-packages"
SYSTEMD_DIR="${TARGET_ROOT%/}/etc/systemd/system"
ETC_KITE_DIR="${TARGET_ROOT%/}/etc/kite-os"

mkdir -p "${SITE_DIR}" "${SYSTEMD_DIR}" "${ETC_KITE_DIR}"
cp -a "${SCRIPT_DIR}/src/kite_ai" "${SITE_DIR}/"
install -m 0644 "${SCRIPT_DIR}/.kiteignore" "${ETC_KITE_DIR}/kiteignore"
install -m 0644 "${SCRIPT_DIR}/systemd/kite-aid.socket" "${SYSTEMD_DIR}/kite-aid.socket"
install -m 0644 "${SCRIPT_DIR}/systemd/kite-aid.service" "${SYSTEMD_DIR}/kite-aid.service"
install -m 0644 "${SCRIPT_DIR}/systemd/kite-index.timer" "${SYSTEMD_DIR}/kite-index.timer"
install -m 0644 "${SCRIPT_DIR}/systemd/kite-index.service" "${SYSTEMD_DIR}/kite-index.service"
