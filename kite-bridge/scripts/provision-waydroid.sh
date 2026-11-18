#!/usr/bin/env bash
set -euo pipefail

export MESA_LOADER_DRIVER_OVERRIDE="crocus"
export LIBVA_DRIVER_NAME="i965"

KITEBRIDGE_DATA_DIR="${KITEBRIDGE_DATA_DIR:-/var/lib/kitebridge}"
WAYDROID_DIR="${WAYDROID_DIR:-/var/lib/waydroid}"
ARM_TRANSLATION="libndk"
ANDROID_TYPE="VANILLA"
BUNDLETOOL_VER="1.17.2"
DRY_RUN=0
VERIFY_ONLY=0

usage() {
  cat <<'EOF'
Usage: provision-waydroid.sh [OPTIONS]
  --arm-translation=libndk|libhoudini|none   ARM binary translation mode (default: libndk)
  --android-type=VANILLA|GAPPS               Waydroid system image type (default: VANILLA)
  --bundletool-ver=<ver>                     bundletool version for .aab conversion (default: 1.17.2)
  --dry-run                                  Print planned steps without modifying host
  --verify                                   Verify binder, PSI, props, and bundletool readiness
EOF
}

for arg in "$@"; do
  case "$arg" in
    --arm-translation=*)
      ARM_TRANSLATION="${arg#*=}"
      ;;
    --android-type=*)
      ANDROID_TYPE="${arg#*=}"
      ;;
    --bundletool-ver=*)
      BUNDLETOOL_VER="${arg#*=}"
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --verify)
      VERIFY_ONLY=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
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

check_kernel_prereqs() {
  if compgen -G "/dev/binder*" >/dev/null 2>&1 || [[ -e /dev/binderfs/binder ]]; then
    printf 'Binder device detected.\n'
  else
    printf 'WARNING: /dev/binder* missing. Trying modprobe binder_linux...\n' >&2
    if [[ "$(id -u)" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
      modprobe binder_linux devices="binder,hwbinder,vndbinder" || true
    fi
  fi

  if [[ -r /proc/pressure/memory ]]; then
    printf 'Kernel PSI (/proc/pressure/memory) enabled.\n'
  else
    printf 'WARNING: Kernel PSI not active; boot kernel with psi=1.\n' >&2
  fi
}

set_prop() {
  local prop_file="$1"
  local key="$2"
  local val="$3"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] prop %s=%s in %s\n' "$key" "$val" "$prop_file"
    return 0
  fi
  touch "$prop_file"
  if grep -qE "^${key}=" "$prop_file"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$prop_file"
  else
    printf '%s=%s\n' "$key" "$val" >> "$prop_file"
  fi
}

if [[ "$VERIFY_ONLY" -eq 1 ]]; then
  check_kernel_prereqs
  PROP_FILE="${WAYDROID_DIR}/waydroid_base.prop"
  if [[ -f "$PROP_FILE" ]] && grep -q '^persist.waydroid.multi_windows=true$' "$PROP_FILE"; then
    printf 'Waydroid multi_windows=true verified in %s\n' "$PROP_FILE"
  else
    echo "persist.waydroid.multi_windows=true missing from ${PROP_FILE}" >&2
    exit 1
  fi
  exit 0
fi

check_kernel_prereqs

# Link Waydroid data under @kitebridge when available
if [[ -d "${KITEBRIDGE_DATA_DIR}/waydroid" && ! -e "$WAYDROID_DIR" ]]; then
  run_cmd ln -s "${KITEBRIDGE_DATA_DIR}/waydroid" "$WAYDROID_DIR"
fi

run_cmd mkdir -p "$WAYDROID_DIR" "${KITEBRIDGE_DATA_DIR}/waydroid/tools" "${KITEBRIDGE_DATA_DIR}/waydroid/aab-cache"

if [[ ! -d "${WAYDROID_DIR}/images" ]] || [[ -z "$(ls -A "${WAYDROID_DIR}/images" 2>/dev/null || true)" ]]; then
  if command -v waydroid >/dev/null 2>&1; then
    run_cmd waydroid init -s "$ANDROID_TYPE"
  else
    printf 'WARNING: waydroid binary not installed yet; skipping waydroid init.\n' >&2
  fi
fi

PROP_FILE="${WAYDROID_DIR}/waydroid_base.prop"
set_prop "$PROP_FILE" "persist.waydroid.multi_windows" "true"
set_prop "$PROP_FILE" "ro.hardware.egl" "mesa"
set_prop "$PROP_FILE" "ro.hardware.gralloc" "gbm"

if [[ "$ARM_TRANSLATION" != "none" ]]; then
  BRIDGE_SO="libndk_translation.so"
  if [[ "$ARM_TRANSLATION" == "libhoudini" ]]; then
    BRIDGE_SO="libhoudini.so"
  fi
  set_prop "$PROP_FILE" "ro.dalvik.vm.isa.arm" "x86"
  set_prop "$PROP_FILE" "ro.dalvik.vm.isa.arm64" "x86_64"
  set_prop "$PROP_FILE" "ro.enable.native.bridge.exec" "1"
  set_prop "$PROP_FILE" "ro.dalvik.vm.native.bridge" "$BRIDGE_SO"
  set_prop "$PROP_FILE" "ro.product.cpu.abilist" "x86_64,x86,arm64-v8a,armeabi-v7a,armeabi"
  set_prop "$PROP_FILE" "ro.product.cpu.abilist64" "x86_64,arm64-v8a"
  set_prop "$PROP_FILE" "ro.product.cpu.abilist32" "x86,armeabi-v7a,armeabi"
fi

# Provision bundletool for .aab -> universal.apk conversion
BUNDLETOOL_JAR="${KITEBRIDGE_DATA_DIR}/waydroid/tools/bundletool-all.jar"
BUNDLETOOL_WRAPPER="${KITEBRIDGE_DATA_DIR}/waydroid/tools/bundletool"
BUNDLETOOL_URL="https://github.com/google/bundletool/releases/download/${BUNDLETOOL_VER}/bundletool-all-${BUNDLETOOL_VER}.jar"

if [[ ! -f "$BUNDLETOOL_JAR" ]]; then
  run_cmd curl -fsSL "$BUNDLETOOL_URL" -o "$BUNDLETOOL_JAR"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '[dry-run] write wrapper %s\n' "$BUNDLETOOL_WRAPPER"
else
  cat > "$BUNDLETOOL_WRAPPER" <<EOF
#!/usr/bin/env bash
exec java -jar "${BUNDLETOOL_JAR}" "\$@"
EOF
  chmod 0755 "$BUNDLETOOL_WRAPPER"
fi

# Sync prewarm state against /run/kite-os/hw-profile.json
HW_PROFILE="/run/kite-os/hw-profile.json"
if [[ "$DRY_RUN" -eq 0 && -f "$HW_PROFILE" ]] && command -v python3 >/dev/null 2>&1; then
  SHOULD_PREWARM="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("1" if d.get("subsystems",{}).get("waydroid",{}).get("prewarm") else "0")' "$HW_PROFILE" 2>/dev/null || echo 0)"
  if [[ "$SHOULD_PREWARM" == "1" ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl start waydroid-container.service || true
  fi
fi

printf 'Waydroid provisioning complete (arm_translation=%s, type=%s).\n' "$ARM_TRANSLATION" "$ANDROID_TYPE"
