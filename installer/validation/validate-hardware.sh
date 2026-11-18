#!/usr/bin/env bash
# KITE_OS Hardware Validation Suite for HP EliteBook Folio 9480m
# Pure GNU Bash + POSIX coreutils (no jq or python3 required).

set -uo pipefail

SCRIPT_NAME="kite-validate-hardware"
MOCK_ROOT="${KITE_MOCK_ROOT:-}"
MOCK_BIN="${KITE_MOCK_BIN:-}"
OUTPUT_JSON=0
STRICT_MODE=0

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
Usage: kite-validate-hardware [OPTIONS]

Validate KITE_OS hardware drivers, kernel devices, Btrfs subvolumes, zram RAM
tiers, storage I/O schedulers, systemd services, and kernel parameters on the
HP EliteBook Folio 9480m (or against an offline mock sysfs/proc/dev root).

Options:
  --json               Emit machine-readable JSON report on stdout
  --mock-root <dir>    Prefix /proc, /sys, /dev, /etc, /run lookups with <dir>
  --mock-bin <dir>     Prepend <dir> to PATH for mocked system binaries
  --strict             Treat WARN checks as failures (exit 1)
  -h, --help           Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json)
            OUTPUT_JSON=1
            shift
            ;;
        --mock-root)
            if [[ $# -lt 2 ]]; then
                echo "Error: --mock-root requires a directory argument" >&2
                exit 2
            fi
            MOCK_ROOT="$2"
            shift 2
            ;;
        --mock-root=*)
            MOCK_ROOT="${1#*=}"
            shift
            ;;
        --mock-bin)
            if [[ $# -lt 2 ]]; then
                echo "Error: --mock-bin requires a directory argument" >&2
                exit 2
            fi
            MOCK_BIN="$2"
            shift 2
            ;;
        --mock-bin=*)
            MOCK_BIN="${1#*=}"
            shift
            ;;
        --strict)
            STRICT_MODE=1
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

MOCK_ROOT="$(normalize_path "$MOCK_ROOT")"
MOCK_ROOT="${MOCK_ROOT%/}"
MOCK_BIN="$(normalize_path "$MOCK_BIN")"
MOCK_BIN="${MOCK_BIN%/}"

# Ensure mock_bin and mock_root/bin take precedence over MSYS2/system PATH
if [[ -n "$MOCK_ROOT" ]]; then
    if [[ -d "${MOCK_ROOT}/usr/bin" ]]; then
        export PATH="${MOCK_ROOT}/usr/bin:${PATH}"
    fi
    if [[ -d "${MOCK_ROOT}/bin" ]]; then
        export PATH="${MOCK_ROOT}/bin:${PATH}"
    fi
fi
if [[ -n "$MOCK_BIN" && -d "$MOCK_BIN" ]]; then
    export PATH="${MOCK_BIN}:${PATH}"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\t'/\\t}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\n'/\\n}"
    printf '%s' "$s"
}

trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

root_path() {
    local p="$1"
    if [[ -n "$MOCK_ROOT" ]]; then
        printf '%s%s' "$MOCK_ROOT" "$p"
    else
        printf '%s' "$p"
    fi
}

# Run a tool honoring KITE_MOCK_<KEY>_OUT, KITE_CMD_<KEY>, or PATH lookup.
# Sets global CMD_OUTPUT and returns 0 if invoked/mocked, 127 if unavailable.
CMD_OUTPUT=""
run_hooked_cmd() {
    local key="$1"
    local bin="$2"
    shift 2

    local mock_out_var="KITE_MOCK_${key}_OUT"
    local cmd_var="KITE_CMD_${key}"
    if [[ -n "${!mock_out_var:-}" ]]; then
        CMD_OUTPUT="${!mock_out_var}"
        return 0
    fi
    local resolved=""
    if [[ -n "${!cmd_var:-}" ]]; then
        resolved="$(normalize_path "${!cmd_var}")"
        if ! command -v "$resolved" >/dev/null 2>&1; then
            CMD_OUTPUT=""
            return 127
        fi
    elif command -v "$bin" >/dev/null 2>&1; then
        resolved="$(command -v "$bin")"
    else
        CMD_OUTPUT=""
        return 127
    fi

    local rc=0
    CMD_OUTPUT="$("$resolved" "$@" 2>&1)" || rc=$?
    return "$rc"
}

# Read an environment key from a file (e.g. 10-kite-haswell.conf or /etc/environment)
read_env_key_from_file() {
    local file="$1"
    local key="$2"
    [[ -f "$file" ]] || return 1
    awk -F= -v k="$key" '
        /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
        {
            lhs = $1
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", lhs)
            if (lhs == k) {
                val = substr($0, index($0, "=") + 1)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
                gsub(/^["\047]|["\047]$/, "", val)
                print val
            }
        }
    ' "$file" | tail -n 1
}

# ---------------------------------------------------------------------------
# Check Ledger
# ---------------------------------------------------------------------------
declare -a CHECK_IDS=()
declare -a CHECK_NAMES=()
declare -a CHECK_STATUSES=()
declare -a CHECK_DETAILS=()

TOTAL_CHECKS=0
PASSED_CHECKS=0
WARNED_CHECKS=0
FAILED_CHECKS=0

record_check() {
    local id="$1"
    local name="$2"
    local status="$3"
    local details="$4"

    CHECK_IDS+=("$id")
    CHECK_NAMES+=("$name")
    CHECK_STATUSES+=("$status")
    CHECK_DETAILS+=("$details")
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    case "$status" in
        PASS) PASSED_CHECKS=$((PASSED_CHECKS + 1)) ;;
        WARN) WARNED_CHECKS=$((WARNED_CHECKS + 1)) ;;
        FAIL) FAILED_CHECKS=$((FAILED_CHECKS + 1)) ;;
    esac
}

# Global detected RAM info (populated in check_zram_ram_tier / precomputed)
DETECTED_RAM_MB=0
DETECTED_RAM_TIER="unknown"

detect_ram_tier() {
    local meminfo_file
    meminfo_file="$(root_path "/proc/meminfo")"
    if [[ ! -r "$meminfo_file" ]]; then
        DETECTED_RAM_MB=0
        DETECTED_RAM_TIER="unknown"
        return 1
    fi
    local mem_kb
    mem_kb="$(awk '/^MemTotal:/ { print $2; exit }' "$meminfo_file" 2>/dev/null || true)"
    if [[ -z "$mem_kb" || ! "$mem_kb" =~ ^[0-9]+$ ]]; then
        DETECTED_RAM_MB=0
        DETECTED_RAM_TIER="unknown"
        return 1
    fi
    DETECTED_RAM_MB=$((mem_kb / 1024))
    if (( DETECTED_RAM_MB < 6144 )); then
        DETECTED_RAM_TIER="4G"
    elif (( DETECTED_RAM_MB <= 12288 )); then
        DETECTED_RAM_TIER="8G"
    else
        DETECTED_RAM_TIER="16G"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Check 1: Mesa OpenGL Driver (crocus, never iris)
# ---------------------------------------------------------------------------
check_mesa_crocus() {
    local id="mesa_crocus"
    local name="Mesa OpenGL Driver (crocus)"
    local conf_file env_file
    conf_file="$(root_path "/etc/environment.d/10-kite-haswell.conf")"
    env_file="$(root_path "/etc/environment")"

    local proc_val="${MESA_LOADER_DRIVER_OVERRIDE:-}"
    local conf_val=""
    local etc_val=""
    [[ -f "$conf_file" ]] && conf_val="$(read_env_key_from_file "$conf_file" "MESA_LOADER_DRIVER_OVERRIDE" || true)"
    [[ -f "$env_file" ]] && etc_val="$(read_env_key_from_file "$env_file" "MESA_LOADER_DRIVER_OVERRIDE" || true)"

    if [[ "$proc_val" == "iris" || "$conf_val" == "iris" || "$etc_val" == "iris" ]]; then
        record_check "$id" "$name" "FAIL" "Forbidden Mesa driver 'iris' configured in MESA_LOADER_DRIVER_OVERRIDE (expected crocus)"
        return
    fi

    local env_pin_ok=0
    if [[ "$conf_val" == "crocus" || "$etc_val" == "crocus" || "$proc_val" == "crocus" ]]; then
        env_pin_ok=1
    fi

    if [[ -f "$conf_file" && "$conf_val" != "crocus" ]]; then
        record_check "$id" "$name" "FAIL" "$conf_file missing MESA_LOADER_DRIVER_OVERRIDE=crocus (got '${conf_val:-unset}')"
        return
    fi

    local gl_out=""
    local gl_ran=0
    local glx_rc=0
    local egl_rc=0
    local glx_out=""
    local egl_out=""

    run_hooked_cmd "GLXINFO" "glxinfo" -B || glx_rc=$?
    glx_out="$CMD_OUTPUT"
    if [[ -n "$glx_out" ]] && printf '%s\n' "$glx_out" | grep -Eiq '(\biris\b|iris_dri)'; then
        record_check "$id" "$name" "FAIL" "Forbidden 'iris' Mesa driver reported by glxinfo/eglinfo (Haswell requires crocus)"
        return
    fi
    if (( glx_rc == 0 )); then
        gl_out="$glx_out"
        gl_ran=1
    else
        run_hooked_cmd "EGLINFO" "eglinfo" || egl_rc=$?
        egl_out="$CMD_OUTPUT"
        if [[ -n "$egl_out" ]] && printf '%s\n' "$egl_out" | grep -Eiq '(\biris\b|iris_dri)'; then
            record_check "$id" "$name" "FAIL" "Forbidden 'iris' Mesa driver reported by glxinfo/eglinfo (Haswell requires crocus)"
            return
        fi
        if (( egl_rc == 0 )); then
            gl_out="$egl_out"
            gl_ran=1
        fi
    fi

    if (( gl_ran == 1 )); then
        if printf '%s\n' "$gl_out" | grep -Eiq '(\biris\b|iris_dri)'; then
            record_check "$id" "$name" "FAIL" "Forbidden 'iris' Mesa driver reported by glxinfo/eglinfo (Haswell requires crocus)"
            return
        fi
        if printf '%s\n' "$gl_out" | grep -Eiq '\bcrocus\b'; then
            record_check "$id" "$name" "PASS" "Mesa crocus driver active and verified (zero iris)"
            return
        fi
        if printf '%s\n' "$gl_out" | grep -Eiq 'HD Graphics 4400' && (( env_pin_ok == 1 )); then
            record_check "$id" "$name" "PASS" "Intel HD Graphics 4400 active with MESA_LOADER_DRIVER_OVERRIDE=crocus"
            return
        fi
        record_check "$id" "$name" "FAIL" "glxinfo/eglinfo did not report crocus driver"
        return
    fi

    if (( env_pin_ok == 1 )); then
        if (( glx_rc != 127 && glx_rc != 0 )) && (( egl_rc == 127 )); then
            record_check "$id" "$name" "PASS" "MESA_LOADER_DRIVER_OVERRIDE=crocus verified in config/environment (glxinfo exited ${glx_rc} without display; eglinfo absent)"
        elif (( glx_rc != 127 && glx_rc != 0 )) || (( egl_rc != 127 && egl_rc != 0 )); then
            record_check "$id" "$name" "PASS" "MESA_LOADER_DRIVER_OVERRIDE=crocus verified in config/environment (glxinfo/eglinfo exited non-zero without display)"
        else
            record_check "$id" "$name" "PASS" "MESA_LOADER_DRIVER_OVERRIDE=crocus verified in config/environment (glxinfo/eglinfo absent)"
        fi
    else
        record_check "$id" "$name" "FAIL" "MESA_LOADER_DRIVER_OVERRIDE=crocus missing and glxinfo/eglinfo unavailable"
    fi
}

# ---------------------------------------------------------------------------
# Check 2: VA-API Driver (i965, never iHD / intel-media-driver)
# ---------------------------------------------------------------------------
check_vaapi_i965() {
    local id="vaapi_i965"
    local name="VA-API Driver (i965)"
    local conf_file env_file
    conf_file="$(root_path "/etc/environment.d/10-kite-haswell.conf")"
    env_file="$(root_path "/etc/environment")"

    local proc_val="${LIBVA_DRIVER_NAME:-}"
    local conf_val=""
    local etc_val=""
    [[ -f "$conf_file" ]] && conf_val="$(read_env_key_from_file "$conf_file" "LIBVA_DRIVER_NAME" || true)"
    [[ -f "$env_file" ]] && etc_val="$(read_env_key_from_file "$env_file" "LIBVA_DRIVER_NAME" || true)"

    local bad_va=""
    for v in "$proc_val" "$conf_val" "$etc_val"; do
        if [[ "$v" == "iHD" || "$v" == "intel-media-driver" ]]; then
            bad_va="$v"
            break
        fi
    done
    if [[ -n "$bad_va" ]]; then
        record_check "$id" "$name" "FAIL" "Forbidden VA-API driver '${bad_va}' configured in LIBVA_DRIVER_NAME (expected i965)"
        return
    fi

    local env_pin_ok=0
    if [[ "$conf_val" == "i965" || "$etc_val" == "i965" || "$proc_val" == "i965" ]]; then
        env_pin_ok=1
    fi

    if [[ -f "$conf_file" && "$conf_val" != "i965" ]]; then
        record_check "$id" "$name" "FAIL" "$conf_file missing LIBVA_DRIVER_NAME=i965 (got '${conf_val:-unset}')"
        return
    fi

    local va_rc=0
    run_hooked_cmd "VAINFO" "vainfo" || va_rc=$?
    if (( va_rc != 127 )); then
        if printf '%s\n' "$CMD_OUTPUT" | grep -Eq '(\biHD\b|iHD_drv_video|intel-media-driver)'; then
            record_check "$id" "$name" "FAIL" "Forbidden iHD VA-API driver reported by vainfo (Haswell requires i965)"
            return
        fi
        if printf '%s\n' "$CMD_OUTPUT" | grep -Eq '\bi965\b'; then
            record_check "$id" "$name" "PASS" "VA-API i965 driver active and verified (zero iHD)"
            return
        fi
        record_check "$id" "$name" "FAIL" "vainfo did not report i965 driver"
        return
    fi

    if (( env_pin_ok == 1 )); then
        record_check "$id" "$name" "PASS" "LIBVA_DRIVER_NAME=i965 verified in config/environment (vainfo absent)"
    else
        record_check "$id" "$name" "FAIL" "LIBVA_DRIVER_NAME=i965 missing and vainfo unavailable"
    fi
}

# ---------------------------------------------------------------------------
# Check 3: Vulkan Driver (anv, max Vulkan 1.2)
# ---------------------------------------------------------------------------
check_vulkan_anv() {
    local id="vulkan_anv"
    local name="Vulkan Driver (anv 1.2)"
    local vk_rc=0
    run_hooked_cmd "VULKANINFO" "vulkaninfo" --summary || vk_rc=$?
    if (( vk_rc == 127 )); then
        record_check "$id" "$name" "WARN" "vulkaninfo not installed/mocked; cannot verify anv Vulkan 1.2 runtime"
        return
    fi
    if (( vk_rc != 0 )) && [[ -z "$CMD_OUTPUT" ]]; then
        run_hooked_cmd "VULKANINFO" "vulkaninfo" || vk_rc=$?
    fi

    local out="$CMD_OUTPUT"
    if [[ -z "$out" ]]; then
        record_check "$id" "$name" "FAIL" "vulkaninfo returned empty output"
        return
    fi

    local has_haswell=0
    if printf '%s\n' "$out" | grep -Eiq '(anv|INTEL_HASWELL|HD Graphics 4400|Intel.*Haswell)'; then
        has_haswell=1
    fi
    if (( has_haswell == 0 )); then
        record_check "$id" "$name" "FAIL" "vulkaninfo did not report Intel Haswell / anv driver"
        return
    fi

    local api_lines
    api_lines="$(printf '%s\n' "$out" | grep -E 'apiVersion[[:space:]]*[:=]' || true)"
    if [[ -z "$api_lines" ]]; then
        record_check "$id" "$name" "FAIL" "Vulkan apiVersion not found in vulkaninfo output"
        return
    fi

    local exceeds_12=0
    local has_12=0
    local bad_ver=""
    local vline
    while IFS= read -r vline; do
        [[ -z "$vline" ]] && continue
        if [[ "$vline" =~ apiVersion[[:space:]]*[:=][[:space:]]*([0-9]+)\.([0-9]+)(\.[0-9]+)?([[:space:]]|\(|$) ]]; then
            local major="${BASH_REMATCH[1]}"
            local minor="${BASH_REMATCH[2]}"
            local ver="${major}.${minor}${BASH_REMATCH[3]}"
            if (( 10#$major > 1 || (10#$major == 1 && 10#$minor >= 3) )); then
                exceeds_12=1
                bad_ver="$ver"
                break
            elif (( 10#$major == 1 && 10#$minor == 2 )); then
                has_12=1
            fi
        else
            exceeds_12=1
            bad_ver="unparsed"
            break
        fi
    done <<< "$api_lines"

    if (( exceeds_12 == 1 )); then
        record_check "$id" "$name" "FAIL" "Vulkan apiVersion (${bad_ver}) exceeds 1.2 max supported by Haswell anv"
        return
    fi

    if (( has_12 == 1 )); then
        record_check "$id" "$name" "PASS" "Vulkan anv driver verified at API version 1.2"
    else
        record_check "$id" "$name" "FAIL" "Vulkan 1.2 apiVersion not confirmed in vulkaninfo output"
    fi
}

# ---------------------------------------------------------------------------
# Check 4: Kernel Devices (/dev/ntsync & /dev/binder*)
# ---------------------------------------------------------------------------
check_kernel_devices() {
    local id="kernel_devices"
    local name="Kernel Devices (ntsync + binder)"
    local ntsync_path binder_glob
    ntsync_path="$(root_path "/dev/ntsync")"
    binder_glob="$(root_path "/dev/binder")"

    local missing=()
    if [[ ! -e "$ntsync_path" ]]; then
        missing+=("/dev/ntsync")
    fi

    local found_binder=0
    local bmatch
    shopt -s nullglob
    for bmatch in "${binder_glob}"* "$(root_path "/dev/hwbinder")" "$(root_path "/dev/vndbinder")" "$(root_path "/dev/binderfs")"; do
        if [[ -e "$bmatch" ]]; then
            found_binder=1
            break
        fi
    done
    shopt -u nullglob

    if (( found_binder == 0 )); then
        missing+=("/dev/binder*")
    fi

    if (( ${#missing[@]} > 0 )); then
        record_check "$id" "$name" "FAIL" "Missing required kernel device(s): ${missing[*]}"
    else
        record_check "$id" "$name" "PASS" "/dev/ntsync and /dev/binder* present"
    fi
}

# ---------------------------------------------------------------------------
# Check 5: Btrfs Layout & Mount Options
# ---------------------------------------------------------------------------
check_btrfs_layout() {
    local id="btrfs_layout"
    local name="Btrfs Subvolumes & Mount Options"
    local mounts_file
    mounts_file="$(root_path "/proc/mounts")"

    local -a targets=("/" "/home" "/var/lib/kitebridge" "/.snapshots")
    local -a subvols=("@" "@home" "@kitebridge" "@snapshots")
    local errors=()

    local have_proc_mounts=0
    if [[ -r "$mounts_file" ]]; then
        have_proc_mounts=1
        local i
        for i in "${!targets[@]}"; do
            local tgt="${targets[$i]}"
            local sub="${subvols[$i]}"
            local line
            line="$(awk -v t="$tgt" '$2 == t && $3 == "btrfs" { print $4; exit }' "$mounts_file" 2>/dev/null || true)"
            if [[ -z "$line" ]]; then
                errors+=("proc/mounts missing btrfs mount for ${tgt} (expected subvol ${sub})")
                continue
            fi
            if ! printf '%s' "$line" | grep -Eq '(^|,)compress=zstd:1(,|$)'; then
                errors+=("${tgt} missing compress=zstd:1 (got: ${line})")
            fi
            if ! printf '%s' "$line" | grep -Eq '(^|,)noatime(,|$)'; then
                errors+=("${tgt} missing noatime (got: ${line})")
            fi
            if ! printf '%s' "$line" | grep -Eq "(^|,)subvol=/?${sub}(,|$)"; then
                errors+=("${tgt} missing subvol=${sub} (got: ${line})")
            fi
        done
    fi

    # Also validate findmnt if mocked or available
    local fm_rc=0
    run_hooked_cmd "FINDMNT" "findmnt" -n -t btrfs -o TARGET,FSTYPE,OPTIONS || fm_rc=$?
    if (( fm_rc != 127 )) && [[ -n "$CMD_OUTPUT" ]]; then
        local fm_out="$CMD_OUTPUT"
        local i
        for i in "${!targets[@]}"; do
            local tgt="${targets[$i]}"
            local sub="${subvols[$i]}"
            local fm_line
            fm_line="$(printf '%s\n' "$fm_out" | awk -v t="$tgt" '$1 == t { print $0; exit }')"
            if [[ -z "$fm_line" ]]; then
                errors+=("findmnt missing ${tgt} (${sub})")
            else
                local fm_opts
                fm_opts="$(printf '%s\n' "$fm_line" | awk '{ print $3 }')"
                if ! printf '%s' "$fm_opts" | grep -Eq '(^|,)compress=zstd:1(,|$)'; then
                    errors+=("findmnt ${tgt} missing compress=zstd:1")
                fi
                if ! printf '%s' "$fm_opts" | grep -Eq '(^|,)noatime(,|$)'; then
                    errors+=("findmnt ${tgt} missing noatime")
                fi
                if ! printf '%s' "$fm_line" | grep -Eq "(subvol=/?|\[/?)${sub}(\]|,| |\$)"; then
                    errors+=("findmnt ${tgt} missing subvolume ${sub}")
                fi
            fi
        done
    elif (( have_proc_mounts == 0 )); then
        errors+=("neither /proc/mounts nor findmnt provided Btrfs mount data")
    fi

    # Also validate btrfs subvolume list if mocked or available
    local bt_rc=0
    run_hooked_cmd "BTRFS" "btrfs" subvolume list / || bt_rc=$?
    if (( bt_rc == 0 )) && [[ -n "$CMD_OUTPUT" ]]; then
        local bt_out="$CMD_OUTPUT"
        local sub
        for sub in "${subvols[@]}"; do
            if ! printf '%s\n' "$bt_out" | grep -Eq "(^|[[:space:]]|/)@${sub#@}([[:space:]]|\$)"; then
                errors+=("btrfs subvolume list missing ${sub}")
            fi
        done
    fi

    if (( ${#errors[@]} > 0 )); then
        local joined
        joined="$(printf '%s; ' "${errors[@]}")"
        record_check "$id" "$name" "FAIL" "${joined%; }"
    else
        record_check "$id" "$name" "PASS" "All 4 Btrfs subvolumes (@, @home, @kitebridge, @snapshots) verified with compress=zstd:1,noatime"
    fi
}

# ---------------------------------------------------------------------------
# Check 6: zram & RAM Tier Scaling (4G / 8G / 16G)
# ---------------------------------------------------------------------------
parse_size_to_bytes() {
    local raw="$1"
    raw="$(trim "$raw")"
    if [[ "$raw" =~ ^[0-9]+$ ]]; then
        printf '%s' "$raw"
        return 0
    fi
    awk -v s="$raw" 'BEGIN {
        if (match(s, /^([0-9]+(\.[0-9]+)?)([KkMmGgTt])[iI]?[Bb]?$/, m)) {
            val = m[1] + 0
            unit = toupper(m[3])
            if (unit == "K") val *= 1024
            else if (unit == "M") val *= 1024 * 1024
            else if (unit == "G") val *= 1024 * 1024 * 1024
            else if (unit == "T") val *= 1024 * 1024 * 1024 * 1024
            printf "%.0f", val
            exit 0
        }
        exit 1
    }'
}

check_zram_ram_tier() {
    local id="zram_ram_tier"
    local name="zram & RAM Tier Tuning"

    if (( DETECTED_RAM_MB <= 0 )); then
        record_check "$id" "$name" "FAIL" "Unable to determine MemTotal from $(root_path "/proc/meminfo")"
        return
    fi

    local expected_percent expected_algo expected_swappiness
    case "$DETECTED_RAM_TIER" in
        4G)
            expected_percent=150
            expected_algo="lz4"
            expected_swappiness=180
            ;;
        8G)
            expected_percent=100
            expected_algo="zstd"
            expected_swappiness=150
            ;;
        16G)
            expected_percent=50
            expected_algo="zstd"
            expected_swappiness=100
            ;;
        *)
            record_check "$id" "$name" "FAIL" "Unknown RAM tier: $DETECTED_RAM_TIER"
            return
            ;;
    esac

    local zram_algo=""
    local zram_bytes=""
    local zram_rc=0
    run_hooked_cmd "ZRAMCTL" "zramctl" --bytes --noheadings --output NAME,ALGORITHM,DISKSIZE || zram_rc=$?
    if (( zram_rc != 127 )) && [[ -n "$CMD_OUTPUT" ]]; then
        local zline
        zline="$(printf '%s\n' "$CMD_OUTPUT" | grep -v '^[[:space:]]*NAME' | head -n 1 || true)"
        if [[ -n "$zline" ]]; then
            local col1 col2 col3
            read -r col1 col2 col3 _ <<<"$zline"
            local c2="${col2#[}"
            c2="${c2%]}"
            local c3="${col3#[}"
            c3="${c3%]}"
            local bytes2="" bytes3=""
            bytes2="$(parse_size_to_bytes "$c2" 2>/dev/null || true)"
            bytes3="$(parse_size_to_bytes "$c3" 2>/dev/null || true)"
            # Handle either NAME ALGO SIZE or NAME DISKSIZE ALGO
            if [[ -n "$bytes3" && -z "$bytes2" ]]; then
                zram_algo="$c2"
                zram_bytes="$bytes3"
            elif [[ -n "$bytes2" && -z "$bytes3" ]]; then
                zram_algo="$c3"
                zram_bytes="$bytes2"
            fi
        fi
    fi

    if [[ -z "$zram_algo" || -z "$zram_bytes" ]]; then
        local sys_algo sys_size
        sys_algo="$(root_path "/sys/block/zram0/comp_algorithm")"
        sys_size="$(root_path "/sys/block/zram0/disksize")"
        if [[ -r "$sys_algo" && -r "$sys_size" ]]; then
            local raw_algo
            raw_algo="$(cat "$sys_algo")"
            if [[ "$raw_algo" =~ \[([a-zA-Z0-9_-]+)\] ]]; then
                zram_algo="${BASH_REMATCH[1]}"
            else
                zram_algo="$(trim "$raw_algo")"
            fi
            zram_bytes="$(trim "$(cat "$sys_size")")"
        fi
    fi

    zram_algo="${zram_algo#[}"
    zram_algo="${zram_algo%]}"

    if [[ -z "$zram_algo" || -z "$zram_bytes" ]]; then
        record_check "$id" "$name" "FAIL" "No active zram device detected for ${DETECTED_RAM_TIER} tier (${DETECTED_RAM_MB} MB)"
        return
    fi

    local errors=()
    if [[ "$zram_algo" != "$expected_algo" ]]; then
        errors+=("zram algorithm '${zram_algo}' != expected '${expected_algo}' for ${DETECTED_RAM_TIER}")
    fi

    local expected_bytes min_bytes max_bytes
    expected_bytes=$(( DETECTED_RAM_MB * 1024 * 1024 * expected_percent / 100 ))
    min_bytes=$(( expected_bytes * 85 / 100 ))
    max_bytes=$(( expected_bytes * 115 / 100 ))
    if [[ ! "$zram_bytes" =~ ^[0-9]+$ ]] || (( zram_bytes < min_bytes || zram_bytes > max_bytes )); then
        errors+=("zram disksize ${zram_bytes} bytes outside +/-15% of expected ${expected_bytes} bytes (${expected_percent}% of ${DETECTED_RAM_MB} MB)")
    fi

    local swappiness_file page_cluster_file
    swappiness_file="$(root_path "/proc/sys/vm/swappiness")"
    page_cluster_file="$(root_path "/proc/sys/vm/page-cluster")"
    if [[ -r "$swappiness_file" ]]; then
        local actual_swap
        actual_swap="$(trim "$(cat "$swappiness_file")")"
        if [[ "$actual_swap" != "$expected_swappiness" ]]; then
            errors+=("vm.swappiness=${actual_swap} != expected ${expected_swappiness} for ${DETECTED_RAM_TIER}")
        fi
    fi
    if [[ -r "$page_cluster_file" ]]; then
        local actual_pc
        actual_pc="$(trim "$(cat "$page_cluster_file")")"
        if [[ "$actual_pc" != "0" ]]; then
            errors+=("vm.page-cluster=${actual_pc} != expected 0")
        fi
    fi

    if (( ${#errors[@]} > 0 )); then
        local joined
        joined="$(printf '%s; ' "${errors[@]}")"
        record_check "$id" "$name" "FAIL" "${joined%; }"
    else
        record_check "$id" "$name" "PASS" "${DETECTED_RAM_TIER} tier (${DETECTED_RAM_MB} MB): zram ${expected_percent}% ${zram_algo} verified"
    fi
}

# ---------------------------------------------------------------------------
# Check 7: Storage I/O Schedulers (rotational=0 -> kyber/none, 1 -> bfq)
# ---------------------------------------------------------------------------
check_storage_schedulers() {
    local id="storage_schedulers"
    local name="Storage I/O Schedulers"
    local block_dir
    block_dir="$(root_path "/sys/block")"

    if [[ ! -d "$block_dir" ]]; then
        record_check "$id" "$name" "FAIL" "Missing sysfs block directory: ${block_dir}"
        return
    fi

    local dev_count=0
    local checked_summary=()
    local errors=()
    local dev_path

    shopt -s nullglob
    for dev_path in "${block_dir}"/*; do
        [[ -d "$dev_path" ]] || continue
        local dev_name="${dev_path##*/}"
        case "$dev_name" in
            loop*|ram*|zram*|dm-*|sr*|md*|nbd*) continue ;;
        esac
        local rot_file="${dev_path}/queue/rotational"
        local sched_file="${dev_path}/queue/scheduler"
        [[ -r "$rot_file" && -r "$sched_file" ]] || continue

        dev_count=$((dev_count + 1))
        local rot raw_sched active_sched
        rot="$(trim "$(cat "$rot_file")")"
        raw_sched="$(trim "$(cat "$sched_file")")"
        if [[ "$raw_sched" =~ \[([a-zA-Z0-9_-]+)\] ]]; then
            active_sched="${BASH_REMATCH[1]}"
        else
            active_sched="${raw_sched%% *}"
        fi

        if [[ "$rot" == "0" ]]; then
            if [[ "$active_sched" != "kyber" && "$active_sched" != "none" ]]; then
                errors+=("${dev_name} (rotational=0 SSD) has scheduler '${active_sched}', expected kyber or none")
            else
                checked_summary+=("${dev_name}:rot=0:${active_sched}")
            fi
        elif [[ "$rot" == "1" ]]; then
            if [[ "$active_sched" != "bfq" ]]; then
                errors+=("${dev_name} (rotational=1 HDD) has scheduler '${active_sched}', expected bfq")
            else
                checked_summary+=("${dev_name}:rot=1:${active_sched}")
            fi
        else
            errors+=("${dev_name} has unexpected rotational value '${rot}'")
        fi
    done
    shopt -u nullglob

    if (( dev_count == 0 )); then
        record_check "$id" "$name" "FAIL" "No physical block devices found under ${block_dir}"
    elif (( ${#errors[@]} > 0 )); then
        local joined
        joined="$(printf '%s; ' "${errors[@]}")"
        record_check "$id" "$name" "FAIL" "${joined%; }"
    else
        record_check "$id" "$name" "PASS" "Storage schedulers verified (${checked_summary[*]})"
    fi
}

# ---------------------------------------------------------------------------
# Check 8: Systemd Services & /run/kite-os/hw-profile.json
# ---------------------------------------------------------------------------
query_service_state() {
    local unit="$1"
    local env_override="$2"

    if [[ -n "$env_override" ]]; then
        printf '%s' "$env_override"
        return 0
    fi

    local state_file
    state_file="$(root_path "/run/systemd/units/${unit}")"
    if [[ -r "$state_file" ]]; then
        trim "$(cat "$state_file")"
        return 0
    fi

    local rc=0
    run_hooked_cmd "SYSTEMCTL" "systemctl" is-active "$unit" || rc=$?
    if (( rc != 127 )); then
        local first_line
        first_line="$(printf '%s\n' "$CMD_OUTPUT" | head -n 1)"
        trim "$first_line"
        return 0
    fi

    printf 'unknown'
    return 1
}

check_systemd_services() {
    local id="systemd_services"
    local name="Systemd Services & Hardware Profile"

    local hw_state power_state
    hw_state="$(query_service_state "kite-hw-tune.service" "${KITE_MOCK_SERVICE_HW_TUNE:-}" || true)"
    power_state="$(query_service_state "kite-power.service" "${KITE_MOCK_SERVICE_POWER:-}" || true)"

    local errors=()
    if [[ "$hw_state" != "active" ]]; then
        errors+=("kite-hw-tune.service state is '${hw_state}' (expected active)")
    fi
    if [[ "$power_state" != "active" ]]; then
        errors+=("kite-power.service state is '${power_state}' (expected active)")
    fi

    if (( ${#errors[@]} > 0 )); then
        local joined
        joined="$(printf '%s; ' "${errors[@]}")"
        record_check "$id" "$name" "FAIL" "${joined%; }"
        return
    fi

    local profile_file
    profile_file="$(root_path "/run/kite-os/hw-profile.json")"
    if [[ ! -r "$profile_file" ]]; then
        record_check "$id" "$name" "WARN" "Services active, but ${profile_file} not present"
        return
    fi

    local profile_raw
    profile_raw="$(cat "$profile_file")"
    local prof_errors=()
    if ! printf '%s\n' "$profile_raw" | grep -Eq '"schema_version"[[:space:]]*:[[:space:]]*1\b'; then
        prof_errors+=("schema_version != 1")
    fi
    if [[ "$DETECTED_RAM_TIER" != "unknown" ]] && ! printf '%s\n' "$profile_raw" | grep -Eq "\"tier\"[[:space:]]*:[[:space:]]*\"${DETECTED_RAM_TIER}\""; then
        prof_errors+=("profile tier mismatch (expected ${DETECTED_RAM_TIER})")
    fi
    if ! printf '%s\n' "$profile_raw" | grep -Eq '"dxvk_version"[[:space:]]*:[[:space:]]*"1\.10\.3"'; then
        prof_errors+=("dxvk_version != 1.10.3")
    fi

    if (( ${#prof_errors[@]} > 0 )); then
        local pjoined
        pjoined="$(printf '%s; ' "${prof_errors[@]}")"
        record_check "$id" "$name" "FAIL" "hw-profile.json contract violation: ${pjoined%; }"
    else
        record_check "$id" "$name" "PASS" "kite-hw-tune.service & kite-power.service active; hw-profile.json v1 verified"
    fi
}

# ---------------------------------------------------------------------------
# Check 9: Kernel Parameters (/proc/cmdline)
# ---------------------------------------------------------------------------
check_kernel_params() {
    local id="kernel_params"
    local name="Haswell Kernel Parameters"
    local cmdline_file
    cmdline_file="$(root_path "/proc/cmdline")"

    if [[ ! -r "$cmdline_file" ]]; then
        record_check "$id" "$name" "FAIL" "Missing kernel cmdline file: ${cmdline_file}"
        return
    fi

    local cmdline
    cmdline="$(cat "$cmdline_file")"
    local -a required=("i915.enable_fbc=1" "i915.fastboot=1" "intel_pstate=active" "psi=1")
    local missing=()
    local param
    for param in "${required[@]}"; do
        if ! printf '%s\n' "$cmdline" | grep -Eq "(^|[[:space:]])${param//./\\.}([[:space:]]|\$)"; then
            missing+=("$param")
        fi
    done

    if (( ${#missing[@]} > 0 )); then
        record_check "$id" "$name" "FAIL" "Missing required kernel param(s): ${missing[*]}"
    else
        record_check "$id" "$name" "PASS" "All required Haswell kernel parameters present (${required[*]})"
    fi
}

# ---------------------------------------------------------------------------
# Check 10: HP Folio 9480m Peripherals (iwlwifi, btusb, e1000e, snd_hda_intel, Synaptics, VFS495)
# ---------------------------------------------------------------------------
has_kernel_module_or_pci() {
    local mod="$1"
    local sys_mod lsmod_out="$2" lspci_out="$3"
    sys_mod="$(root_path "/sys/module/${mod}")"
    if [[ -d "$sys_mod" ]]; then
        return 0
    fi
    if [[ -n "$lsmod_out" ]] && printf '%s\n' "$lsmod_out" | grep -Eq "(^|[[:space:]])${mod}([[:space:]]|\$)"; then
        return 0
    fi
    if [[ -n "$lspci_out" ]] && printf '%s\n' "$lspci_out" | grep -Eiq "\b${mod}\b"; then
        return 0
    fi
    return 1
}

check_folio9480m_peripherals() {
    local id="folio9480m_peripherals"
    local name="Folio 9480m Peripherals"

    local sys_mod_dir input_devs usb_bus_dir
    sys_mod_dir="$(root_path "/sys/module")"
    input_devs="$(root_path "/proc/bus/input/devices")"
    usb_bus_dir="$(root_path "/sys/bus/usb/devices")"

    local lsmod_out="" lspci_out="" lsusb_out="" libinput_out=""
    local have_probe=0

    [[ -d "$sys_mod_dir" || -r "$input_devs" || -d "$usb_bus_dir" ]] && have_probe=1

    local rc=0
    run_hooked_cmd "LSMOD" "lsmod" || rc=$?
    if (( rc != 127 )) && [[ -n "$CMD_OUTPUT" ]]; then
        lsmod_out="$CMD_OUTPUT"
        have_probe=1
    fi

    rc=0
    run_hooked_cmd "LSPCI" "lspci" -k || rc=$?
    if (( rc != 127 )) && [[ -n "$CMD_OUTPUT" ]]; then
        lspci_out="$CMD_OUTPUT"
        have_probe=1
    fi

    rc=0
    run_hooked_cmd "LSUSB" "lsusb" || rc=$?
    if (( rc != 127 )) && [[ -n "$CMD_OUTPUT" ]]; then
        lsusb_out="$CMD_OUTPUT"
        have_probe=1
    fi

    rc=0
    run_hooked_cmd "LIBINPUT" "libinput" list-devices || rc=$?
    if (( rc != 127 )) && [[ -n "$CMD_OUTPUT" ]]; then
        libinput_out="$CMD_OUTPUT"
        have_probe=1
    fi

    if (( have_probe == 0 )); then
        record_check "$id" "$name" "WARN" "Peripheral sysfs/proc and probe tools (lsmod/lspci/lsusb/libinput) unavailable"
        return
    fi

    local missing=()
    local verified=()

    if has_kernel_module_or_pci "iwlwifi" "$lsmod_out" "$lspci_out"; then
        verified+=("iwlwifi")
    else
        missing+=("iwlwifi(Wireless 7260)")
    fi

    local has_btusb=0
    if has_kernel_module_or_pci "btusb" "$lsmod_out" "$lsusb_out"; then
        has_btusb=1
    elif [[ -n "$lsusb_out" ]] && printf '%s\n' "$lsusb_out" | grep -Eiq '8087:07dc'; then
        has_btusb=1
    elif [[ -d "$usb_bus_dir" ]]; then
        local bdev
        shopt -s nullglob
        for bdev in "${usb_bus_dir}"/*; do
            if [[ -r "${bdev}/idVendor" && -r "${bdev}/idProduct" ]]; then
                local bvid bpid
                bvid="$(trim "$(cat "${bdev}/idVendor")")"
                bpid="$(trim "$(cat "${bdev}/idProduct")")"
                if [[ "${bvid,,}" == "8087" && "${bpid,,}" == "07dc" ]]; then
                    has_btusb=1
                    break
                fi
            fi
        done
        shopt -u nullglob
    fi
    if (( has_btusb == 1 )); then
        verified+=("btusb")
    else
        missing+=("btusb(Bluetooth)")
    fi

    if has_kernel_module_or_pci "e1000e" "$lsmod_out" "$lspci_out"; then
        verified+=("e1000e")
    else
        missing+=("e1000e(I218-LM)")
    fi

    if has_kernel_module_or_pci "snd_hda_intel" "$lsmod_out" "$lspci_out"; then
        verified+=("snd_hda_intel")
    else
        missing+=("snd_hda_intel(IDT 92HD91BXX)")
    fi

    local has_synaptics=0
    if [[ -r "$input_devs" ]] && grep -Eiq '(synaptics|touchpad)' "$input_devs"; then
        has_synaptics=1
    elif [[ -n "$libinput_out" ]] && printf '%s\n' "$libinput_out" | grep -Eiq '(synaptics|touchpad)'; then
        has_synaptics=1
    elif [[ -d "$(root_path "/sys/module/psmouse")" ]]; then
        has_synaptics=1
    fi
    if (( has_synaptics == 1 )); then
        verified+=("synaptics")
    else
        missing+=("synaptics(LuxPad)")
    fi

    local has_vfs495=0
    if [[ -n "$lsusb_out" ]] && printf '%s\n' "$lsusb_out" | grep -Eiq '138a:003f|vfs495'; then
        has_vfs495=1
    elif [[ -d "$usb_bus_dir" ]]; then
        local udev
        shopt -s nullglob
        for udev in "${usb_bus_dir}"/*; do
            if [[ -r "${udev}/idVendor" && -r "${udev}/idProduct" ]]; then
                local vid pid
                vid="$(trim "$(cat "${udev}/idVendor")")"
                pid="$(trim "$(cat "${udev}/idProduct")")"
                if [[ "${vid,,}" == "138a" && "${pid,,}" == "003f" ]]; then
                    has_vfs495=1
                    break
                fi
            fi
        done
        shopt -u nullglob
    fi
    if (( has_vfs495 == 1 )); then
        verified+=("vfs495(138a:003f)")
    fi

    if (( ${#missing[@]} > 0 )); then
        record_check "$id" "$name" "FAIL" "Missing Folio 9480m peripheral driver(s): ${missing[*]}"
    elif (( has_vfs495 == 0 )) && [[ -n "$lsusb_out" || -d "$usb_bus_dir" ]]; then
        record_check "$id" "$name" "WARN" "Core peripherals verified (${verified[*]}); Validity VFS495 (138a:003f) fingerprint reader not detected"
    else
        record_check "$id" "$name" "PASS" "Folio 9480m peripherals verified (${verified[*]})"
    fi
}

# ---------------------------------------------------------------------------
# Execute All Checks
# ---------------------------------------------------------------------------
detect_ram_tier || true

check_mesa_crocus
check_vaapi_i965
check_vulkan_anv
check_kernel_devices
check_btrfs_layout
check_zram_ram_tier
check_storage_schedulers
check_systemd_services
check_kernel_params
check_folio9480m_peripherals

OVERALL_STATUS="PASS"
EXIT_CODE=0
if (( FAILED_CHECKS > 0 )); then
    OVERALL_STATUS="FAIL"
    EXIT_CODE=1
elif (( STRICT_MODE == 1 && WARNED_CHECKS > 0 )); then
    OVERALL_STATUS="FAIL"
    EXIT_CODE=1
elif (( WARNED_CHECKS > 0 )); then
    OVERALL_STATUS="WARN"
fi

if (( OUTPUT_JSON == 1 )); then
    printf '{\n'
    printf '  "schema_version": 1,\n'
    printf '  "hardware_target": "HP EliteBook Folio 9480m",\n'
    printf '  "mock_root": "%s",\n' "$(json_escape "$MOCK_ROOT")"
    printf '  "ram_mb": %d,\n' "$DETECTED_RAM_MB"
    printf '  "ram_tier": "%s",\n' "$(json_escape "$DETECTED_RAM_TIER")"
    printf '  "summary": {\n'
    printf '    "total": %d,\n' "$TOTAL_CHECKS"
    printf '    "passed": %d,\n' "$PASSED_CHECKS"
    printf '    "warned": %d,\n' "$WARNED_CHECKS"
    printf '    "failed": %d,\n' "$FAILED_CHECKS"
    printf '    "status": "%s"\n' "$OVERALL_STATUS"
    printf '  },\n'
    printf '  "checks": [\n'
    for idx in "${!CHECK_IDS[@]}"; do
        comma=","
        if (( idx == ${#CHECK_IDS[@]} - 1 )); then
            comma=""
        fi
        printf '    {"id": "%s", "name": "%s", "status": "%s", "details": "%s"}%s\n' \
            "$(json_escape "${CHECK_IDS[$idx]}")" \
            "$(json_escape "${CHECK_NAMES[$idx]}")" \
            "$(json_escape "${CHECK_STATUSES[$idx]}")" \
            "$(json_escape "${CHECK_DETAILS[$idx]}")" \
            "$comma"
    done
    printf '  ]\n'
    printf '}\n'
else
    printf 'KITE_OS Hardware Validation — HP EliteBook Folio 9480m\n'
    printf 'RAM: %d MB (Tier: %s)\n' "$DETECTED_RAM_MB" "$DETECTED_RAM_TIER"
    for idx in "${!CHECK_IDS[@]}"; do
        printf '[%s] %s: %s\n' "${CHECK_STATUSES[$idx]}" "${CHECK_IDS[$idx]}" "${CHECK_DETAILS[$idx]}"
    done
    printf 'Summary: %d/%d passed, %d warned, %d failed (status: %s)\n' \
        "$PASSED_CHECKS" "$TOTAL_CHECKS" "$WARNED_CHECKS" "$FAILED_CHECKS" "$OVERALL_STATUS"
fi

exit "$EXIT_CODE"
