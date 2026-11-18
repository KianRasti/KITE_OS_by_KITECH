#!/usr/bin/env bash
set -euo pipefail

# Haswell Intel HD 4400 strict driver & DXVK 1.10.3 pins
export MESA_LOADER_DRIVER_OVERRIDE="crocus"
export LIBVA_DRIVER_NAME="i965"
unset VKD3D_CONFIG VKD3D_FEATURE_LEVEL VKD3D_SHADER_DEBUG PROTON_USE_VKD3D || true

REQUIRED_DXVK_VERSION="1.10.3"
DXVK_TARBALL_URL="https://github.com/doitsujin/dxvk/releases/download/v1.10.3/dxvk-1.10.3.tar.gz"
DXVK_TARBALL_SHA256="8d1a3c912761b450c879f98478ae64f6f6639e40ce6848170a0f6b8596fd53c6"

KITEBRIDGE_DATA_DIR="${KITEBRIDGE_DATA_DIR:-/var/lib/kitebridge}"
RUNTIME_FLAVOR="wine-cachyos"
WINEPREFIX="${WINEPREFIX:-${KITEBRIDGE_DATA_DIR}/wine/prefixes/default}"
PROTON_TAG="${PROTON_TAG:-GE-Proton9-20}"
DRY_RUN=0
VERIFY_ONLY=0
SKIP_DOWNLOAD=0

usage() {
  cat <<'EOF'
Usage: provision-wine.sh [OPTIONS]
  --runtime=wine-cachyos|proton-ge   Wine runtime flavor (default: wine-cachyos)
  --prefix=<path>                    Target Wine prefix
  --proton-tag=<tag>                 GE-Proton release tag when --runtime=proton-ge
  --dry-run                          Print actions without executing
  --verify                           Verify DXVK 1.10.3 pin, DLLs, and prefix manifest
  --skip-download                    Skip network downloads (use cached archives)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --runtime=*)
      RUNTIME_FLAVOR="${arg#*=}"
      ;;
    --prefix=*)
      WINEPREFIX="${arg#*=}"
      ;;
    --proton-tag=*)
      PROTON_TAG="${arg#*=}"
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --verify)
      VERIFY_ONLY=1
      ;;
    --skip-download)
      SKIP_DOWNLOAD=1
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

# Layer 1: Strict DXVK 1.10.3 pin
if [[ "${DXVK_VER:-1.10.3}" != "$REQUIRED_DXVK_VERSION" ]]; then
  echo "ERROR: DXVK_VER must be strictly ${REQUIRED_DXVK_VERSION} (got '${DXVK_VER:-}')." >&2
  exit 1
fi
if [[ "${DXVK_VERSION:-1.10.3}" != "$REQUIRED_DXVK_VERSION" ]]; then
  echo "ERROR: DXVK_VERSION must be strictly ${REQUIRED_DXVK_VERSION} (got '${DXVK_VERSION:-}')." >&2
  exit 1
fi
export DXVK_VER="$REQUIRED_DXVK_VERSION"

DXVK_DIR="${KITEBRIDGE_DATA_DIR}/wine/dxvk/${REQUIRED_DXVK_VERSION}"
RUNNERS_DIR="${KITEBRIDGE_DATA_DIR}/wine/runners"
CACHE_DIR="${KITEBRIDGE_DATA_DIR}/cache"

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

verify_setup() {
  if [[ "$DXVK_VER" != "$REQUIRED_DXVK_VERSION" ]]; then
    echo "DXVK pin mismatch" >&2
    return 1
  fi
  if [[ "$MESA_LOADER_DRIVER_OVERRIDE" != "crocus" || "$LIBVA_DRIVER_NAME" != "i965" ]]; then
    echo "Haswell driver pins missing" >&2
    return 1
  fi
  for arch in x64 x32; do
    for dll in d3d9.dll d3d10core.dll d3d11.dll dxgi.dll; do
      if [[ ! -f "${DXVK_DIR}/${arch}/${dll}" ]]; then
        echo "Missing DXVK ${REQUIRED_DXVK_VERSION} DLL: ${DXVK_DIR}/${arch}/${dll}" >&2
        return 1
      fi
    done
  done
  if find "${WINEPREFIX}/drive_c/windows" -maxdepth 2 -iname 'vkd3d*.dll' 2>/dev/null | grep -q .; then
    echo "Forbidden vkd3d DLL found inside Wine prefix" >&2
    return 1
  fi
  if [[ ! -f "${WINEPREFIX}/.kitebridge-manifest.json" ]]; then
    echo "Missing prefix manifest: ${WINEPREFIX}/.kitebridge-manifest.json" >&2
    return 1
  fi
  printf 'Verified Wine prefix %s with DXVK %s and WineD3D GL (crocus/i965).\n' "$WINEPREFIX" "$REQUIRED_DXVK_VERSION"
}

if [[ "$VERIFY_ONLY" -eq 1 ]]; then
  verify_setup
  exit 0
fi

if [[ -c /dev/ntsync ]]; then
  export WINE_NTSYNC=1
  export WINEESYNC=0
  export WINEFSYNC=0
  printf '/dev/ntsync detected: WINE_NTSYNC=1 enabled.\n'
else
  printf 'WARNING: /dev/ntsync char device not present; ensure ntsync kernel module is loaded.\n' >&2
fi

resolve_wine_bin() {
  if [[ "$RUNTIME_FLAVOR" == "proton-ge" ]]; then
    local p_bin="${RUNNERS_DIR}/${PROTON_TAG}/files/bin/wine"
    if [[ -x "$p_bin" ]]; then
      printf '%s' "$p_bin"
      return 0
    fi
    if [[ "$SKIP_DOWNLOAD" -eq 0 ]]; then
      run_cmd mkdir -p "$RUNNERS_DIR" "$CACHE_DIR"
      local p_url="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${PROTON_TAG}/${PROTON_TAG}.tar.gz"
      local s_url="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${PROTON_TAG}/${PROTON_TAG}.sha512sum"
      run_cmd curl -fsSL "$p_url" -o "${CACHE_DIR}/${PROTON_TAG}.tar.gz"
      run_cmd curl -fsSL "$s_url" -o "${CACHE_DIR}/${PROTON_TAG}.sha512sum"
      if [[ "$DRY_RUN" -eq 0 ]]; then
        (cd "$CACHE_DIR" && sha512sum -c "${PROTON_TAG}.sha512sum")
        tar -xzf "${CACHE_DIR}/${PROTON_TAG}.tar.gz" -C "$RUNNERS_DIR"
      fi
    fi
    printf '%s' "$p_bin"
    return 0
  fi

  if [[ -x /opt/wine-cachyos/bin/wine ]]; then
    printf '/opt/wine-cachyos/bin/wine'
  elif command -v wine-cachyos >/dev/null 2>&1; then
    command -v wine-cachyos
  elif command -v wine >/dev/null 2>&1; then
    command -v wine
  else
    echo "wine-cachyos not found. Install via: sudo pacman -S --needed wine-cachyos" >&2
    printf 'wine'
  fi
}

WINE_BIN="$(resolve_wine_bin)"
WINESERVER_BIN="$(dirname "$WINE_BIN")/wineserver"
if [[ ! -x "$WINESERVER_BIN" ]]; then
  WINESERVER_BIN="wineserver"
fi

# Provision DXVK 1.10.3 with strict SHA-256 verification
run_cmd mkdir -p "${DXVK_DIR}/x64" "${DXVK_DIR}/x32" "$CACHE_DIR"
DXVK_TARBALL="${CACHE_DIR}/dxvk-${REQUIRED_DXVK_VERSION}.tar.gz"
if [[ "$SKIP_DOWNLOAD" -eq 0 && ! -f "$DXVK_TARBALL" ]]; then
  run_cmd curl -fsSL "$DXVK_TARBALL_URL" -o "$DXVK_TARBALL"
fi

if [[ "$DRY_RUN" -eq 0 && -f "$DXVK_TARBALL" ]]; then
  printf '%s  %s\n' "$DXVK_TARBALL_SHA256" "$DXVK_TARBALL" | sha256sum -c -
  TMP_EXTRACT="$(mktemp -d)"
  trap 'rm -rf "$TMP_EXTRACT"' EXIT
  tar -xzf "$DXVK_TARBALL" -C "$TMP_EXTRACT"
  for arch in x64 x32; do
    for dll in d3d9.dll d3d10core.dll d3d11.dll dxgi.dll; do
      install -m 0644 "${TMP_EXTRACT}/dxvk-${REQUIRED_DXVK_VERSION}/${arch}/${dll}" "${DXVK_DIR}/${arch}/${dll}"
    done
  done
fi

# Initialize 64-bit prefix and enforce DXVK 1.10.3 + WineD3D GL overrides
run_cmd mkdir -p "$WINEPREFIX"
if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '[dry-run] WINEARCH=win64 WINEPREFIX=%s %s wineboot --init\n' "$WINEPREFIX" "$WINE_BIN"
  printf '[dry-run] install DXVK %s DLLs into %s/drive_c/windows/{system32,syswow64}\n' "$REQUIRED_DXVK_VERSION" "$WINEPREFIX"
else
  export WINEARCH="win64"
  export WINEPREFIX
  if [[ ! -f "${WINEPREFIX}/system.reg" ]]; then
    WINEDLLOVERRIDES="mscoree,mshtml=" "$WINE_BIN" wineboot --init
    "$WINESERVER_BIN" -w || true
  fi

  mkdir -p "${WINEPREFIX}/drive_c/windows/system32" "${WINEPREFIX}/drive_c/windows/syswow64"
  for dll in d3d9.dll d3d10core.dll d3d11.dll dxgi.dll; do
    if [[ -f "${DXVK_DIR}/x64/${dll}" ]]; then
      install -m 0644 "${DXVK_DIR}/x64/${dll}" "${WINEPREFIX}/drive_c/windows/system32/${dll}"
    fi
    if [[ -f "${DXVK_DIR}/x32/${dll}" ]]; then
      install -m 0644 "${DXVK_DIR}/x32/${dll}" "${WINEPREFIX}/drive_c/windows/syswow64/${dll}"
    fi
  done

  find "${WINEPREFIX}/drive_c/windows" -maxdepth 2 -iname 'vkd3d*.dll' -delete 2>/dev/null || true

  "$WINE_BIN" reg add 'HKCU\Software\Wine\Direct3D' /v renderer /t REG_SZ /d gl /f >/dev/null 2>&1 || true
  for dll in d3d9 d3d10core d3d11 dxgi; do
    "$WINE_BIN" reg add 'HKCU\Software\Wine\DllOverrides' /v "$dll" /t REG_SZ /d 'native,builtin' /f >/dev/null 2>&1 || true
  done
  "$WINE_BIN" reg add 'HKCU\Software\Wine\DllOverrides' /v d3d12 /t REG_SZ /d builtin /f >/dev/null 2>&1 || true
  "$WINE_BIN" reg add 'HKCU\Software\Wine\DllOverrides' /v d3d12core /t REG_SZ /d builtin /f >/dev/null 2>&1 || true

  USER_NAME="${USER:-kite}"
  USER_DIR="${WINEPREFIX}/drive_c/users/${USER_NAME}"
  mkdir -p "$USER_DIR"
  for folder in Desktop Documents Downloads; do
    mkdir -p "${HOME}/${folder}"
    if [[ -d "${USER_DIR}/${folder}" && ! -L "${USER_DIR}/${folder}" ]]; then
      rmdir "${USER_DIR}/${folder}" 2>/dev/null || mv "${USER_DIR}/${folder}" "${USER_DIR}/${folder}.bak"
    fi
    ln -sfn "${HOME}/${folder}" "${USER_DIR}/${folder}"
  done

  cat > "${WINEPREFIX}/.kitebridge-manifest.json" <<EOF
{
  "schema_version": 1,
  "dxvk_version": "${REQUIRED_DXVK_VERSION}",
  "wined3d_dx12": true,
  "mesa_driver": "crocus",
  "libva_driver": "i965"
}
EOF
fi

printf 'Provisioned Wine prefix (%s) with DXVK %s.\n' "$WINEPREFIX" "$REQUIRED_DXVK_VERSION"
