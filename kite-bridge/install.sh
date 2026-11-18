#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="/usr/local"
DESTDIR=""
STATE_DIR="/var/lib/kitebridge"
DRY_RUN=0
SKIP_DATABASES=0

usage() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]
  --prefix <dir>        Installation prefix (default: /usr/local)
  --destdir <dir>       Staging root directory (default: "")
  --state-dir <dir>     KiteBridge @kitebridge data root (default: /var/lib/kitebridge)
  --dry-run             Print planned actions without modifying files
  --skip-databases      Skip update-mime-database and update-desktop-database
  -h, --help            Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; }
      PREFIX="$2"
      shift 2
      ;;
    --destdir)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; }
      DESTDIR="$2"
      shift 2
      ;;
    --state-dir)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; }
      STATE_DIR="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-databases)
      SKIP_DATABASES=1
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

PYTHON_BIN="${PYTHON_BIN:-python3}"
BIN_DIR="${DESTDIR}${PREFIX}/bin"
SHARE_DIR="${DESTDIR}${PREFIX}/share/kite-bridge"
MIME_DIR="${DESTDIR}/usr/share/mime/packages"
APPS_DIR="${DESTDIR}/usr/share/applications"
TARGET_STATE="${DESTDIR}${STATE_DIR}"

# 1. Install Python package (PEP 668 --break-system-packages aware)
if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '[dry-run] %s -m pip install --no-build-isolation --no-deps --break-system-packages --prefix %s %s\n' \
    "$PYTHON_BIN" "$PREFIX" "$SCRIPT_DIR"
else
  PIP_ARGS=(-m pip install --no-build-isolation --no-deps --prefix "$PREFIX")
  if [[ -n "$DESTDIR" ]]; then
    PIP_ARGS+=(--root "$DESTDIR")
  fi
  if "$PYTHON_BIN" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
    PIP_ARGS+=(--break-system-packages)
  fi
  "$PYTHON_BIN" "${PIP_ARGS[@]}" "$SCRIPT_DIR"
fi

# 2. Install CLI wrapper
run_cmd mkdir -p "$BIN_DIR"
if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '[dry-run] write CLI wrapper -> %s/kite-bridge\n' "$BIN_DIR"
else
  cat > "${BIN_DIR}/kite-bridge" <<EOF
#!/usr/bin/env bash
exec "${PYTHON_BIN}" -m kite_bridge "\$@"
EOF
  chmod 0755 "${BIN_DIR}/kite-bridge"
fi

# 3. Install QML wizard & MIME/desktop assets
run_cmd mkdir -p "$SHARE_DIR" "$MIME_DIR" "$APPS_DIR"
run_cmd install -m 0644 "${SCRIPT_DIR}/mime/GlassInstallerWizard.qml" "${SHARE_DIR}/GlassInstallerWizard.qml"
run_cmd install -m 0644 "${SCRIPT_DIR}/mime/kitebridge-mime.xml" "${MIME_DIR}/kitebridge-mime.xml"
run_cmd install -m 0644 "${SCRIPT_DIR}/mime/kitebridge-open.desktop" "${APPS_DIR}/kitebridge-open.desktop"
run_cmd install -m 0644 "${SCRIPT_DIR}/mime/kitebridge-wizard.desktop" "${APPS_DIR}/kitebridge-wizard.desktop"
run_cmd install -m 0644 "${SCRIPT_DIR}/mime/kitebridge-app-template.desktop" "${APPS_DIR}/kitebridge-app-template.desktop"

if [[ -z "$DESTDIR" && "$SKIP_DATABASES" -eq 0 ]]; then
  if command -v update-mime-database >/dev/null 2>&1; then
    run_cmd update-mime-database /usr/share/mime
  fi
  if command -v update-desktop-database >/dev/null 2>&1; then
    run_cmd update-desktop-database /usr/share/applications
  fi
fi

# 4. Create /var/lib/kitebridge (@kitebridge) directory hierarchy
SUBDIRS=(
  "wine/prefixes"
  "wine/dxvk/1.10.3"
  "wine/runners"
  "waydroid/images"
  "waydroid/data"
  "waydroid/overlay"
  "waydroid/tools"
  "waydroid/aab-cache"
  "macos/osx-kvm"
  "macos/images"
  "macos/mounts"
  "macos/snapshots"
  "macos/darling/prefix"
  "icons"
  "cache"
  "cgroups"
)

for sub in "${SUBDIRS[@]}"; do
  run_cmd mkdir -p "${TARGET_STATE}/${sub}"
done

if [[ -z "$DESTDIR" && "$DRY_RUN" -eq 0 ]] && command -v findmnt >/dev/null 2>&1; then
  if mount_info="$(findmnt -n -o FSTYPE,OPTIONS "$STATE_DIR" 2>/dev/null || true)"; then
    if [[ -n "$mount_info" ]]; then
      printf 'Verified @kitebridge mount at %s: %s\n' "$STATE_DIR" "$mount_info"
    fi
  fi
fi

printf 'KiteBridge installation complete (prefix=%s, state=%s)\n' "$PREFIX" "$TARGET_STATE"
