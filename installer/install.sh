#!/usr/bin/env bash
# KITE_OS Installer Staging Script
# Stages Calamares configuration/branding and Folio 9480m validation tools
# into a target root filesystem (--root or DESTDIR).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR"
TARGET_ROOT="${KITE_OS_TARGET_ROOT:-${DESTDIR:-/}}"
DRY_RUN=0
SKIP_VALIDATION=0

normalize_path() {
    local raw="$1"
    if [[ -z "$raw" ]]; then
        printf ''
        return
    fi
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -u "$raw" 2>/dev/null || printf '%s' "${raw//\\//}"
    else
        printf '%s' "${raw//\\//}"
    fi
}

usage() {
    cat <<'EOF'
Usage: install.sh [OPTIONS]

Stage KITE_OS Calamares configuration, Aero Blue Glass branding, and HP Folio
9480m hardware validation tools into a target rootfs.

Options:
  --root <dir>         Target root filesystem directory (overrides DESTDIR)
  --source <dir>       Source installer directory (defaults to script dir)
  --dry-run            Print staging operations without writing files
  --skip-validation    Skip staging validation script and checklist
  -h, --help           Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)
            if [[ $# -lt 2 ]]; then
                echo "Error: --root requires a directory argument" >&2
                exit 2
            fi
            TARGET_ROOT="$2"
            shift 2
            ;;
        --root=*)
            TARGET_ROOT="${1#*=}"
            shift
            ;;
        --source)
            if [[ $# -lt 2 ]]; then
                echo "Error: --source requires a directory argument" >&2
                exit 2
            fi
            SOURCE_DIR="$2"
            shift 2
            ;;
        --source=*)
            SOURCE_DIR="${1#*=}"
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --skip-validation)
            SKIP_VALIDATION=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: unknown argument '$1'" >&2
            usage >&2
            exit 2
            ;;
    esac
done

SOURCE_DIR="$(normalize_path "$SOURCE_DIR")"
SOURCE_DIR="${SOURCE_DIR%/}"
TARGET_ROOT="$(normalize_path "$TARGET_ROOT")"
if [[ "$TARGET_ROOT" != "/" ]]; then
    TARGET_ROOT="${TARGET_ROOT%/}"
fi

join_target() {
    local rel="$1"
    if [[ "$TARGET_ROOT" == "/" ]]; then
        printf '/%s' "${rel#/}"
    else
        printf '%s/%s' "$TARGET_ROOT" "${rel#/}"
    fi
}

run_install_dir() {
    local dst="$1"
    if (( DRY_RUN == 1 )); then
        printf '[DRY-RUN] install -d -m 0755 %s\n' "$dst"
    else
        install -d -m 0755 "$dst"
    fi
}

run_install_file() {
    local mode="$1"
    local src="$2"
    local dst="$3"
    if (( DRY_RUN == 1 )); then
        printf '[DRY-RUN] install -m %s %s %s\n' "$mode" "$src" "$dst"
    else
        install -m "$mode" "$src" "$dst"
    fi
}

# Pre-flight validation
CALAMARES_SRC="${SOURCE_DIR}/calamares"
VALIDATION_SRC="${SOURCE_DIR}/validation"

if [[ ! -f "${CALAMARES_SRC}/settings.conf" ]]; then
    echo "Error: missing ${CALAMARES_SRC}/settings.conf" >&2
    exit 1
fi
if [[ ! -d "${CALAMARES_SRC}/modules" ]]; then
    echo "Error: missing ${CALAMARES_SRC}/modules directory" >&2
    exit 1
fi
if [[ ! -d "${CALAMARES_SRC}/branding/kite-os" ]]; then
    echo "Error: missing ${CALAMARES_SRC}/branding/kite-os directory" >&2
    exit 1
fi
if (( SKIP_VALIDATION == 0 )); then
    if [[ ! -f "${VALIDATION_SRC}/validate-hardware.sh" ]]; then
        echo "Error: missing ${VALIDATION_SRC}/validate-hardware.sh" >&2
        exit 1
    fi
    if [[ ! -f "${VALIDATION_SRC}/folio9480m-checklist.md" ]]; then
        echo "Error: missing ${VALIDATION_SRC}/folio9480m-checklist.md" >&2
        exit 1
    fi
fi

# 1. Stage Calamares settings and module configs
CALAMARES_DST="$(join_target "etc/calamares")"
MODULES_DST="$(join_target "etc/calamares/modules")"
BRANDING_DST="$(join_target "etc/calamares/branding/kite-os")"

run_install_dir "$CALAMARES_DST"
run_install_dir "$MODULES_DST"
run_install_dir "$BRANDING_DST"

run_install_file "0644" "${CALAMARES_SRC}/settings.conf" "${CALAMARES_DST}/settings.conf"

shopt -s nullglob
for mod_conf in "${CALAMARES_SRC}/modules/"*.conf; do
    run_install_file "0644" "$mod_conf" "${MODULES_DST}/$(basename "$mod_conf")"
done
shopt -u nullglob

# 2. Stage Calamares branding tree dynamically
while IFS= read -r -d '' src_file; do
    rel_path="${src_file#"${CALAMARES_SRC}/branding/kite-os/"}"
    dst_file="${BRANDING_DST}/${rel_path}"
    run_install_dir "$(dirname "$dst_file")"
    run_install_file "0644" "$src_file" "$dst_file"
done < <(find "${CALAMARES_SRC}/branding/kite-os" -type f -print0 | sort -z)

# 3. Stage Folio 9480m hardware validation tools
if (( SKIP_VALIDATION == 0 )); then
    BIN_DST="$(join_target "usr/local/bin")"
    SHARE_VAL_DST="$(join_target "usr/share/kite-os/validation")"

    run_install_dir "$BIN_DST"
    run_install_dir "$SHARE_VAL_DST"

    run_install_file "0755" "${VALIDATION_SRC}/validate-hardware.sh" "${BIN_DST}/kite-validate-hardware"
    run_install_file "0755" "${VALIDATION_SRC}/validate-hardware.sh" "${SHARE_VAL_DST}/validate-hardware.sh"
    run_install_file "0644" "${VALIDATION_SRC}/folio9480m-checklist.md" "${SHARE_VAL_DST}/folio9480m-checklist.md"
fi

printf 'KITE_OS installer staging complete -> %s\n' "$TARGET_ROOT"
