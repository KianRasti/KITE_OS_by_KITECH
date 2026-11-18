#!/usr/bin/env bash
set -euo pipefail

SRC_ROOT="/opt/kite-os-src"
STAMP_FILE="/var/lib/kite-os/.staged"

if [[ -f "${STAMP_FILE}" && "${1:-}" != "--force" ]]; then
  exit 0
fi

mkdir -p /etc/environment.d /var/lib/kite-os /etc/kite-os /var/lib/kitebridge

for component in kite-hw-tune kite-shell kite-bridge kite-ai installer; do
  if [[ -f "${SRC_ROOT}/${component}/install.sh" ]]; then
    echo "[kite-stage] Installing ${component} from ${SRC_ROOT}/${component}..."
    if [[ "${component}" == "kite-shell" ]]; then
      KITE_OS_TARGET_ROOT="/" bash "${SRC_ROOT}/${component}/install.sh" --skel
    else
      KITE_OS_TARGET_ROOT="/" bash "${SRC_ROOT}/${component}/install.sh"
    fi
  fi
done

if [[ -d /etc/skel/.config && -d /home/kite ]]; then
  mkdir -p /home/kite/.config
  cp -a /etc/skel/.config/. /home/kite/.config/
  if id kite >/dev/null 2>&1; then
    chown -R kite:kite /home/kite/.config || true
  fi
fi

# Live ISO convenience: passwordless root/kite + tty1 autologin into Hyprland
passwd -d root >/dev/null 2>&1 || true
if id kite >/dev/null 2>&1; then
  passwd -d kite >/dev/null 2>&1 || true
  mkdir -p /etc/systemd/system/getty@tty1.service.d
  cat <<'EOF' > /etc/systemd/system/getty@tty1.service.d/autologin.conf
[Service]
ExecStart=
ExecStart=-/sbin/agetty -o '-p -f -- \\u' --noclear --autologin kite %I $TERM
EOF
  if [[ -d /home/kite ]] && ! grep -q 'exec Hyprland' /home/kite/.bash_profile 2>/dev/null; then
    cat <<'EOF' >> /home/kite/.bash_profile
[[ -z "${WAYLAND_DISPLAY:-}" && "$(tty)" == "/dev/tty1" ]] && exec Hyprland
EOF
    chown kite:kite /home/kite/.bash_profile || true
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  for unit in NetworkManager.service bluetooth.service thermald.service kite-hw-tune.service kite-power.service kite-aid.socket kite-index.timer; do
    if [[ -f "/etc/systemd/system/${unit}" || -f "/usr/lib/systemd/system/${unit}" ]]; then
      systemctl enable "${unit}" || true
    fi
  done
  if [[ -d /run/systemd/system ]]; then
    sys_state="$(systemctl is-system-running 2>/dev/null || true)"
    if [[ -n "${sys_state}" && "${sys_state}" != "offline" ]]; then
      systemctl start --no-block kite-hw-tune.service kite-power.service || true
    fi
  fi
fi

touch "${STAMP_FILE}"
