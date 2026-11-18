#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTDIR=""
NO_ENABLE=0

usage() {
    cat <<'EOF'
Usage: install.sh [--destdir <path>] [--no-enable]
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --destdir)
            if [[ $# -lt 2 ]]; then
                echo "Error: --destdir requires a path argument" >&2
                exit 2
            fi
            DESTDIR="$2"
            shift 2
            ;;
        --no-enable)
            NO_ENABLE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

DESTDIR="${DESTDIR%/}"
if [[ -n "$DESTDIR" ]] && command -v cygpath >/dev/null 2>&1; then
    DESTDIR="$(cygpath -u "$DESTDIR")"
    DESTDIR="${DESTDIR%/}"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

install_purelib_fallback() {
    local purelib
    purelib="$("$PYTHON_BIN" -c 'import os, sys, sysconfig; p = sysconfig.get_path("purelib"); print(f"/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages" if os.name == "nt" else p)')"
    install -d "${DESTDIR}${purelib}"
    cp -r "${SCRIPT_DIR}/kite_hw_tune" "${DESTDIR}${purelib}/"
    rm -rf "${DESTDIR}${purelib}/kite_hw_tune/__pycache__"
}

# Install Python package (require both pip and setuptools on POSIX; otherwise purelib copy)
if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1 \
    && KITE_INSTALL_DESTDIR="$DESTDIR" "$PYTHON_BIN" -c "import os, setuptools; assert os.name != 'nt' or not os.environ.get('KITE_INSTALL_DESTDIR')" >/dev/null 2>&1; then
    PIP_ARGS=(install --no-build-isolation --no-deps --root="${DESTDIR:-/}")
    if "$PYTHON_BIN" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
        PIP_ARGS+=(--break-system-packages)
    fi
    if ! "$PYTHON_BIN" -m pip "${PIP_ARGS[@]}" "$SCRIPT_DIR"; then
        echo "Warning: pip install failed; falling back to purelib copy" >&2
        install_purelib_fallback
    fi
else
    install_purelib_fallback
fi

# Ensure /usr/local/bin wrappers match systemd ExecStart paths
install -d "${DESTDIR}/usr/local/bin"
cat > "${DESTDIR}/usr/local/bin/kite-hw-tune" <<'EOF'
#!/usr/bin/env python3
import sys
from kite_hw_tune.cli import main_hw_tune
sys.exit(main_hw_tune())
EOF
chmod 0755 "${DESTDIR}/usr/local/bin/kite-hw-tune"

cat > "${DESTDIR}/usr/local/bin/kite-power" <<'EOF'
#!/usr/bin/env python3
import sys
from kite_hw_tune.cli import main_power
sys.exit(main_power())
EOF
chmod 0755 "${DESTDIR}/usr/local/bin/kite-power"

# Install systemd units
install -Dm644 "${SCRIPT_DIR}/systemd/kite-hw-tune.service" "${DESTDIR}/etc/systemd/system/kite-hw-tune.service"
install -Dm644 "${SCRIPT_DIR}/systemd/kite-power.service" "${DESTDIR}/etc/systemd/system/kite-power.service"

# Install udev rules
install -Dm644 "${SCRIPT_DIR}/udev/99-kite-power.rules" "${DESTDIR}/etc/udev/rules.d/99-kite-power.rules"
install -Dm644 "${SCRIPT_DIR}/udev/99-kite-storage.rules" "${DESTDIR}/etc/udev/rules.d/99-kite-storage.rules"

# Install hardware & thermal configs
install -Dm644 "${SCRIPT_DIR}/config/10-kite-haswell.conf" "${DESTDIR}/etc/environment.d/10-kite-haswell.conf"
install -Dm644 "${SCRIPT_DIR}/config/modprobe-kite-haswell.conf" "${DESTDIR}/etc/modprobe.d/kite-haswell.conf"
install -Dm644 "${SCRIPT_DIR}/config/99-kite-base.conf" "${DESTDIR}/etc/sysctl.d/99-kite-base.conf"
install -Dm644 "${SCRIPT_DIR}/config/thermal-conf.xml" "${DESTDIR}/etc/thermald/thermal-conf.xml"

if [[ "$NO_ENABLE" -eq 0 ]]; then
    if [[ -z "$DESTDIR" && -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable kite-hw-tune.service kite-power.service
        if command -v udevadm >/dev/null 2>&1; then
            udevadm control --reload-rules || true
        fi
    else
        install -d "${DESTDIR}/etc/systemd/system/multi-user.target.wants"
        ln -sf /etc/systemd/system/kite-hw-tune.service "${DESTDIR}/etc/systemd/system/multi-user.target.wants/kite-hw-tune.service"
        ln -sf /etc/systemd/system/kite-power.service "${DESTDIR}/etc/systemd/system/multi-user.target.wants/kite-power.service"
    fi
fi
