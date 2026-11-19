#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX="${PREFIX:-/usr/local}"
DESTDIR="${DESTDIR:-}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
EXPLICIT_CONFIG_DIR=0
INSTALL_SKEL=0
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: install.sh [OPTIONS]

Idempotent installer for KITE_OS kite-shell (Hyprland + Quickshell + kite-settings + preview).

Options:
  --prefix PATH       Installation prefix (default: /usr/local)
  --destdir PATH      Staging root directory (default: empty)
  --config-dir PATH   User config directory (default: ${XDG_CONFIG_HOME:-$HOME/.config})
  --skel              Also stage defaults into ${DESTDIR}/etc/skel/.config
  --dry-run           Print planned actions without modifying files
  -h, --help          Show this help message
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            if [ "$#" -lt 2 ]; then
                echo "Error: --prefix requires a path argument" >&2
                exit 2
            fi
            PREFIX="$2"
            shift 2
            ;;
        --destdir)
            if [ "$#" -lt 2 ]; then
                echo "Error: --destdir requires a path argument" >&2
                exit 2
            fi
            DESTDIR="$2"
            shift 2
            ;;
        --config-dir)
            if [ "$#" -lt 2 ]; then
                echo "Error: --config-dir requires a path argument" >&2
                exit 2
            fi
            CONFIG_DIR="$2"
            EXPLICIT_CONFIG_DIR=1
            shift 2
            ;;
        --skel)
            INSTALL_SKEL=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
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
    if [ "${DRY_RUN}" -eq 1 ]; then
        printf '[dry-run]'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

seed_if_missing() {
    local target="$1"
    local content="$2"
    if [ -f "${target}" ]; then
        echo "[skip] preserving existing ${target}"
        return 0
    fi
    if [ "${DRY_RUN}" -eq 1 ]; then
        echo "[dry-run] seed default ${target}"
        return 0
    fi
    mkdir -p "$(dirname "${target}")"
    printf '%s\n' "${content}" > "${target}"
}

DEFAULT_SETTINGS_JSON='{
  "schema_version": 1,
  "theme_preset": "Aero Blue",
  "accent_color": "#38BDF8",
  "taskbar_alignment": "center",
  "transparency": 0.72,
  "blur_radius": 6,
  "specular_edge_brightness": 0.35,
  "corner_radius": 12,
  "animation_speed": 1.0,
  "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
  "wallpaper": "aero-glass-wave",
  "battery_glass_autosimplify": true,
  "mitigations_off_requested": false
}'

DEFAULT_HYPR_GLASS_CONF='# Default HD 4400 AC baseline seeded by kite-shell/install.sh
decoration {
    rounding = 12
    blur {
        enabled = true
        size = 6
        passes = 2
        xray = true
        new_optimizations = true
        ignore_opacity = true
    }
}'

SHARE_ROOT="${DESTDIR}${PREFIX}/share/kite-shell"
BIN_DIR="${DESTDIR}${PREFIX}/bin"
APPS_DIR="${DESTDIR}${PREFIX}/share/applications"

run_cmd mkdir -p "${SHARE_ROOT}/hypr" "${SHARE_ROOT}/quickshell/components" \
    "${SHARE_ROOT}/settings/kite_settings" "${SHARE_ROOT}/settings/theme" \
    "${SHARE_ROOT}/settings/components" "${SHARE_ROOT}/settings/pages" \
    "${SHARE_ROOT}/preview" "${BIN_DIR}" "${APPS_DIR}"

# 1. Stage Hyprland configs (.conf + .lua)
for f in "${SCRIPT_DIR}/hypr/"*.conf "${SCRIPT_DIR}/hypr/"*.lua; do
    [ -f "${f}" ] || continue
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/hypr/"
done

# 2. Stage Quickshell QML
for f in "${SCRIPT_DIR}/quickshell/"*.qml; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/quickshell/"
done
for f in "${SCRIPT_DIR}/quickshell/components/"*.qml; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/quickshell/components/"
done

# 3. Stage kite-settings studio & Python controller
run_cmd install -m 755 "${SCRIPT_DIR}/settings/kite-settings" "${SHARE_ROOT}/settings/kite-settings"
run_cmd install -m 644 "${SCRIPT_DIR}/settings/SettingsApp.qml" "${SHARE_ROOT}/settings/SettingsApp.qml"
run_cmd install -m 644 "${SCRIPT_DIR}/settings/pyproject.toml" "${SHARE_ROOT}/settings/pyproject.toml"
for f in "${SCRIPT_DIR}/settings/kite_settings/"*.py; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/settings/kite_settings/"
done
for f in "${SCRIPT_DIR}/settings/theme/"*; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/settings/theme/"
done
for f in "${SCRIPT_DIR}/settings/components/"*.qml; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/settings/components/"
done
for f in "${SCRIPT_DIR}/settings/pages/"*.qml; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/settings/pages/"
done

# Launcher symlink/copy in PREFIX/bin
run_cmd install -m 755 "${SCRIPT_DIR}/settings/kite-settings" "${BIN_DIR}/kite-settings"

# Desktop entry for kite-settings
DESKTOP_ENTRY='[Desktop Entry]
Type=Application
Name=KITE_OS Settings Studio
Comment=Live Glass UI customization and Folio 9480m hardware profile
Exec=kite-settings
Icon=preferences-desktop
Categories=Settings;DesktopSettings;
Terminal=false'

if [ "${DRY_RUN}" -eq 1 ]; then
    echo "[dry-run] write ${APPS_DIR}/kite-settings.desktop"
else
    printf '%s\n' "${DESKTOP_ENTRY}" > "${APPS_DIR}/kite-settings.desktop"
fi

# 4. Stage preview simulator
for f in "${SCRIPT_DIR}/preview/"*; do
    run_cmd install -m 644 "${f}" "${SHARE_ROOT}/preview/"
done

# 5. Deploy to user config directory (or staged CONFIG_DIR)
deploy_config_tree() {
    local cfg_root="$1"
    run_cmd mkdir -p "${cfg_root}/hypr" "${cfg_root}/quickshell/components" "${cfg_root}/kite-os"
    for f in "${SCRIPT_DIR}/hypr/"*.conf "${SCRIPT_DIR}/hypr/"*.lua; do
        [ -f "${f}" ] || continue
        run_cmd install -m 644 "${f}" "${cfg_root}/hypr/"
    done
    for f in "${SCRIPT_DIR}/quickshell/"*.qml; do
        run_cmd install -m 644 "${f}" "${cfg_root}/quickshell/"
    done
    for f in "${SCRIPT_DIR}/quickshell/components/"*.qml; do
        run_cmd install -m 644 "${f}" "${cfg_root}/quickshell/components/"
    done
    seed_if_missing "${cfg_root}/kite-os/settings.json" "${DEFAULT_SETTINGS_JSON}"
    seed_if_missing "${cfg_root}/hypr/kite-glass-runtime.conf" "${DEFAULT_HYPR_GLASS_CONF}"
}

if [ -n "${DESTDIR}" ] && [ "${INSTALL_SKEL}" -eq 1 ] && [ "${EXPLICIT_CONFIG_DIR}" -eq 0 ]; then
    echo "[skip] --destdir with --skel and no explicit --config-dir: skipping ${DESTDIR}${CONFIG_DIR}"
else
    deploy_config_tree "${DESTDIR}${CONFIG_DIR}"
fi

if [ "${INSTALL_SKEL}" -eq 1 ]; then
    deploy_config_tree "${DESTDIR}/etc/skel/.config"
fi

# 6. Safe Hyprland reload guard
if [ "${DRY_RUN}" -eq 0 ] && [ -z "${DESTDIR}" ] && [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && command -v hyprctl >/dev/null 2>&1; then
    hyprctl reload || true
fi

echo "kite-shell installation complete (prefix=${PREFIX}, destdir=${DESTDIR:-<none>})."
