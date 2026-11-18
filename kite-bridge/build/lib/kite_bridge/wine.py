"""Windows subsystem: Wine-CachyOS/Proton-GE, /dev/ntsync, strict DXVK 1.10.3, and WineD3D DX12."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from . import LIBVA_DRIVER_PIN, MESA_DRIVER_PIN, REQUIRED_DXVK_VERSION
from .abstractions import (
    HwProfileReader,
    LocalPrefixFilesystem,
    PosixSystemProbe,
    PrefixFilesystem,
    ProcessRunner,
    SubprocessRunner,
    SystemProbe,
)
from .config import BridgeConfig, validate_dxvk_version
from .hw_profile import JsonHwProfileReader
from .models import (
    CommandResult,
    DxvkVersionViolationError,
    HwProfile,
    Platform,
    RouteDecision,
    RuntimeNotFoundError,
    Vkd3dForbiddenError,
)

DXVK_DLL_NAMES = ("d3d9", "d3d10core", "d3d11", "dxgi")
REQUIRED_WINEDLLOVERRIDES = (
    "d3d9=n,b;d3d10core=n,b;d3d11=n,b;dxgi=n,b;d3d12=b;d3d12core=b"
)
FORBIDDEN_DX_ENV_KEYS = (
    "VKD3D_CONFIG",
    "VKD3D_FEATURE_LEVEL",
    "VKD3D_SHADER_DEBUG",
    "PROTON_USE_VKD3D",
)

_SHLLINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")


@dataclass(frozen=True)
class WineRuntime:
    binary: str
    wineserver: str
    flavor: str  # "wine-cachyos", "proton-ge", "wine", "virtual"
    available: bool = True


@dataclass(frozen=True)
class ParsedShortcut:
    target_windows_path: str | None
    target_posix_path: str | None
    working_dir: str | None
    arguments: str | None
    icon_location: str | None


def parse_lnk(data: bytes, *, prefix_path: str = "/var/lib/kitebridge/wine/prefixes/default") -> ParsedShortcut | None:
    """Pure-Python MS-SHLLINK (.lnk) binary parser."""
    if len(data) < 76:
        return None
    header_size = struct.unpack_from("<I", data, 0)[0]
    if header_size != 0x4C or data[4:20] != _SHLLINK_CLSID:
        return None

    link_flags = struct.unpack_from("<I", data, 20)[0]
    has_id_list = bool(link_flags & 0x01)
    has_link_info = bool(link_flags & 0x02)
    has_name = bool(link_flags & 0x04)
    has_rel_path = bool(link_flags & 0x08)
    has_work_dir = bool(link_flags & 0x10)
    has_args = bool(link_flags & 0x20)
    has_icon = bool(link_flags & 0x40)
    is_unicode = bool(link_flags & 0x80)

    offset = 76
    if has_id_list:
        if offset + 2 > len(data):
            return None
        id_list_size = struct.unpack_from("<H", data, offset)[0]
        offset += 2 + id_list_size

    local_base_path: str | None = None
    common_suffix: str | None = None
    if has_link_info and offset + 4 <= len(data):
        info_start = offset
        info_size = struct.unpack_from("<I", data, info_start)[0]
        if info_size >= 28 and info_start + info_size <= len(data):
            info_flags = struct.unpack_from("<I", data, info_start + 8)[0]
            if info_flags & 0x01:
                local_base_off = struct.unpack_from("<I", data, info_start + 16)[0]
                if 0 < local_base_off < info_size:
                    end = data.find(b"\x00", info_start + local_base_off, info_start + info_size)
                    if end != -1:
                        local_base_path = data[info_start + local_base_off:end].decode("cp1252", errors="replace")
            common_off = struct.unpack_from("<I", data, info_start + 24)[0]
            if 0 < common_off < info_size:
                end = data.find(b"\x00", info_start + common_off, info_start + info_size)
                if end != -1:
                    common_suffix = data[info_start + common_off:end].decode("cp1252", errors="replace")
        offset += info_size

    def _read_string_data() -> str | None:
        nonlocal offset
        if offset + 2 > len(data):
            return None
        char_count = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        byte_len = char_count * 2 if is_unicode else char_count
        if offset + byte_len > len(data):
            return None
        raw = data[offset:offset + byte_len]
        offset += byte_len
        return raw.decode("utf-16le" if is_unicode else "cp1252", errors="replace")

    if has_name:
        _read_string_data()
    rel_path = _read_string_data() if has_rel_path else None
    working_dir = _read_string_data() if has_work_dir else None
    arguments = _read_string_data() if has_args else None
    icon_loc = _read_string_data() if has_icon else None

    target_win = local_base_path
    if target_win and common_suffix:
        target_win = target_win.rstrip("\\") + "\\" + common_suffix.lstrip("\\")
    if not target_win and rel_path:
        target_win = rel_path

    target_posix = windows_path_to_posix(target_win, prefix_path=prefix_path) if target_win else None
    return ParsedShortcut(
        target_windows_path=target_win,
        target_posix_path=target_posix,
        working_dir=working_dir,
        arguments=arguments,
        icon_location=icon_loc,
    )


def windows_path_to_posix(win_path: str, *, prefix_path: str) -> str | None:
    """Convert Wine C:\\... or Z:\\... path into POSIX path inside prefix."""
    cleaned = win_path.strip().replace("\\", "/")
    if len(cleaned) >= 2 and cleaned[1] == ":":
        drive = cleaned[0].upper()
        rest = cleaned[2:].lstrip("/")
        if drive == "C":
            return f"{prefix_path.rstrip('/')}/drive_c/{rest}"
        if drive == "Z":
            return f"/{rest}"
    return None


class WineRuntimeSelector:
    """Discovers Wine-CachyOS (preferred) or GE-Proton runners."""

    def __init__(
        self,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.probe = probe or PosixSystemProbe()
        self.config = config or BridgeConfig.from_env(probe=self.probe)

    @staticmethod
    def _sibling_wineserver(wine_bin: str) -> str:
        p = PurePosixPath(wine_bin)
        if str(p.parent) in ("", "."):
            return "wineserver"
        return str(p.parent / "wineserver")

    def select_runtime(
        self,
        preferred: str | None = None,
        *,
        env: Mapping[str, str] | None = None,
        allow_virtual: bool = False,
    ) -> WineRuntime:
        source_env = env if env is not None else os.environ
        override = preferred or source_env.get("KITEBRIDGE_WINE_BIN")
        if override:
            resolved = self.runner.which(override) or (override if self.probe.exists(override) else None)
            if resolved:
                flavor = "proton-ge" if "proton" in resolved.lower() else "wine-cachyos" if "cachyos" in resolved.lower() else "wine"
                return WineRuntime(binary=resolved, wineserver=self._sibling_wineserver(resolved), flavor=flavor)
            if allow_virtual:
                return WineRuntime(binary=override, wineserver="wineserver", flavor="virtual", available=False)
            raise RuntimeNotFoundError(f"Requested Wine binary '{override}' was not found.")

        # 1. Wine-CachyOS preferred
        for candidate in ("/opt/wine-cachyos/bin/wine", "wine-cachyos", "wine"):
            if candidate.startswith("/"):
                if self.probe.exists(candidate):
                    return WineRuntime(
                        binary=candidate,
                        wineserver=self._sibling_wineserver(candidate),
                        flavor="wine-cachyos",
                    )
            else:
                resolved = self.runner.which(candidate)
                if resolved:
                    flavor = "wine-cachyos"
                    if candidate == "wine":
                        ver_res = self.runner.run([resolved, "--version"])
                        ver_text = (ver_res.stdout + ver_res.stderr).lower()
                        if "cachyos" in ver_text or "staging" in ver_text:
                            flavor = "wine-cachyos"
                        else:
                            flavor = "wine"
                    return WineRuntime(
                        binary=resolved,
                        wineserver=self._sibling_wineserver(resolved),
                        flavor=flavor,
                    )

        # 2. GE-Proton runners
        proton_patterns = (
            f"{self.config.data_dir}/wine/runners/GE-Proton*/files/bin/wine",
            f"{self.config.xdg_data_home}/kitebridge/wine/runners/GE-Proton*/files/bin/wine",
            "/usr/share/steam/compatibilitytools.d/GE-Proton*/files/bin/wine",
        )
        proton_candidates: list[str] = []
        for pattern in proton_patterns:
            proton_candidates.extend(self.probe.glob(pattern))
        if proton_candidates:
            proton_candidates.sort(key=self._proton_sort_key, reverse=True)
            chosen = proton_candidates[0]
            return WineRuntime(
                binary=chosen,
                wineserver=self._sibling_wineserver(chosen),
                flavor="proton-ge",
            )

        if allow_virtual:
            return WineRuntime(binary="wine", wineserver="wineserver", flavor="virtual", available=False)
        raise RuntimeNotFoundError(
            "No Wine-CachyOS or GE-Proton runtime found. Run `kite-bridge setup wine` or `scripts/provision-wine.sh`."
        )

    @staticmethod
    def _proton_sort_key(path: str) -> tuple[int, ...]:
        nums = [int(n) for n in re.findall(r"\d+", path)]
        return tuple(nums)


class WineSubsystem:
    """Manages Wine-CachyOS/ntsync prefixes, strict DXVK 1.10.3 pinning, and file launch."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        hw_reader: HwProfileReader | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self.hw_reader = hw_reader or JsonHwProfileReader(probe=self.probe)
        self.selector = WineRuntimeSelector(runner=self.runner, probe=self.probe, config=self.config)

    def check_ntsync(self) -> bool:
        return self.probe.is_char_device("/dev/ntsync") or self.probe.exists("/dev/ntsync")

    def build_env(
        self,
        *,
        prefix: str | None = None,
        base_env: Mapping[str, str] | None = None,
        profile: HwProfile | None = None,
        debug_ntsync: bool = False,
        strict_ntsync: bool = False,
    ) -> tuple[dict[str, str], list[str]]:
        """Build hardened Wine env enforcing Haswell crocus/i965, /dev/ntsync, and DXVK 1.10.3."""
        caller_env = dict(base_env) if base_env is not None else {}
        check_env = base_env if base_env is not None else os.environ
        warnings: list[str] = []

        # Layer 1: Env guard against non-1.10.3 DXVK versions and VKD3D
        for ver_key in ("DXVK_VER", "DXVK_VERSION"):
            if ver_key in check_env:
                validate_dxvk_version(check_env[ver_key])
        if check_env.get("PROTON_USE_VKD3D", "").strip() == "1":
            raise Vkd3dForbiddenError(
                "PROTON_USE_VKD3D=1 is forbidden on Intel HD 4400; DX12 must route to WineD3D OpenGL 4.6 (crocus)."
            )

        # Layer 2: Hardware profile validation
        active_profile = profile or self.hw_reader.read(self.config.hw_profile_path)
        validate_dxvk_version(active_profile.wine_dxvk_version)

        target_prefix = (prefix or self.config.wine_prefix).replace("\\", "/")

        out_env: dict[str, str] = {}
        for k, v in caller_env.items():
            if k in FORBIDDEN_DX_ENV_KEYS:
                continue
            out_env[k] = v

        # Mandatory Haswell GPU & DXVK 1.10.3 pins
        out_env["MESA_LOADER_DRIVER_OVERRIDE"] = MESA_DRIVER_PIN
        out_env["LIBVA_DRIVER_NAME"] = LIBVA_DRIVER_PIN
        out_env["DXVK_VER"] = REQUIRED_DXVK_VERSION
        out_env["WINEPREFIX"] = target_prefix
        out_env["WINEARCH"] = "win64"
        out_env["WINE_D3D_CONFIG"] = "renderer=gl"
        out_env["DXVK_STATE_CACHE"] = "1"
        out_env["DXVK_STATE_CACHE_PATH"] = f"{target_prefix}/dxvk-cache"

        # Merge non-D3D user overrides safely while locking D3D9/10/11/DXGI & D3D12
        user_overrides = caller_env.get("WINEDLLOVERRIDES", "")
        out_env["WINEDLLOVERRIDES"] = self._merge_dll_overrides(user_overrides)

        # /dev/ntsync detection
        ntsync_ok = self.check_ntsync()
        if ntsync_ok:
            out_env["WINE_NTSYNC"] = "1"
            out_env["PROTON_USE_NTSYNC"] = "1"
            out_env["WINEESYNC"] = "0"
            out_env["WINEFSYNC"] = "0"
            out_env["PROTON_NO_ESYNC"] = "1"
            out_env["PROTON_NO_FSYNC"] = "1"
            if debug_ntsync or check_env.get("KITEBRIDGE_DEBUG_NTSYNC") == "1":
                out_env["WINEDEBUG"] = "+ntsync"
        else:
            if strict_ntsync:
                raise RuntimeNotFoundError("/dev/ntsync character device is missing and strict_ntsync=True.")
            warnings.append("/dev/ntsync not detected; falling back to standard wineserver synchronization.")

        return out_env, warnings

    @staticmethod
    def _merge_dll_overrides(user_overrides: str) -> str:
        protected = {"d3d9", "d3d10core", "d3d11", "dxgi", "d3d12", "d3d12core"}
        extras: list[str] = []
        for token in user_overrides.split(";"):
            token = token.strip()
            if not token or "=" not in token:
                continue
            dll_part = token.split("=", 1)[0].strip().lower()
            dlls = [d.strip() for d in dll_part.split(",") if d.strip()]
            if any(d in protected for d in dlls):
                continue
            extras.append(token)
        if extras:
            return f"{REQUIRED_WINEDLLOVERRIDES};{';'.join(extras)}"
        return REQUIRED_WINEDLLOVERRIDES

    def verify_prefix(self, prefix: str | None = None) -> list[str]:
        """Layer 3 & 4 prefix validation: manifest DXVK == 1.10.3, no vkd3d DLLs, no native d3d12."""
        target = (prefix or self.config.wine_prefix).replace("\\", "/")
        warnings: list[str] = []

        # Check forbidden vkd3d DLLs in system32 / syswow64
        for arch_dir in ("drive_c/windows/system32", "drive_c/windows/syswow64"):
            full_dir = f"{target}/{arch_dir}"
            if self.fs.exists(full_dir):
                for entry in self.fs.list_dir(full_dir):
                    lower = entry.lower()
                    if lower.startswith("vkd3d") and lower.endswith(".dll"):
                        raise Vkd3dForbiddenError(
                            f"Forbidden DX12 translation library '{full_dir}/{entry}' found in Wine prefix."
                        )

        manifest_path = f"{target}/.kitebridge-manifest.json"
        if self.fs.exists(manifest_path):
            data = json.loads(self.fs.read_text(manifest_path))
            manifest_ver = str(data.get("dxvk_version", "")).strip()
            validate_dxvk_version(manifest_ver)
            if not data.get("wined3d_dx12", True):
                raise Vkd3dForbiddenError("Prefix manifest disables WineD3D DX12 routing.")

            dll_hashes = data.get("dll_sha256") or {}
            for rel_dll, expected_sha in dll_hashes.items():
                dll_path = f"{target}/{rel_dll.lstrip('/')}"
                if not self.fs.exists(dll_path):
                    raise DxvkVersionViolationError(f"Expected DXVK 1.10.3 DLL missing: {dll_path}")
                actual_sha = hashlib.sha256(self.fs.read_bytes(dll_path)).hexdigest()
                if actual_sha != expected_sha:
                    raise DxvkVersionViolationError(
                        f"DXVK DLL checksum mismatch at '{dll_path}': expected {expected_sha}, got {actual_sha}"
                    )
        else:
            warnings.append(f"Prefix manifest '{manifest_path}' not present yet.")

        user_reg = f"{target}/user.reg"
        if self.fs.exists(user_reg):
            reg_text = self.fs.read_text(user_reg)
            in_overrides = False
            for line in reg_text.splitlines():
                stripped = line.strip()
                if stripped.startswith("["):
                    in_overrides = "software\\wine\\dlloverrides" in stripped.lower().replace("\\\\", "\\")
                    continue
                if in_overrides and stripped.lower().startswith('"d3d12"='):
                    val = stripped.split("=", 1)[1].strip().strip('"').lower()
                    if "native" in val:
                        raise Vkd3dForbiddenError(
                            "Wine user.reg overrides d3d12 to native; must remain builtin (WineD3D OpenGL)."
                        )
        return warnings

    def map_user_folders(self, prefix: str | None = None, *, home_dir: str | None = None, username: str | None = None) -> list[str]:
        """Link prefix Desktop, Documents, Downloads to host ~/ folders without clobbering user data."""
        target_prefix = (prefix or self.config.wine_prefix).replace("\\", "/")
        host_home = (home_dir or self.config.home_dir).replace("\\", "/").rstrip("/")
        resolved_user = username or self.config.user_name or os.environ.get("USER", "kite")
        user_root = f"{target_prefix}/drive_c/users/{resolved_user}"
        self.fs.mkdir(user_root, parents=True)

        mapped: list[str] = []
        for folder in ("Desktop", "Documents", "Downloads"):
            host_dir = f"{host_home}/{folder}"
            self.fs.mkdir(host_dir, parents=True)
            link_path = f"{user_root}/{folder}"
            if self.fs.exists(link_path) and not self.fs.is_symlink(link_path):
                if self.fs.is_dir(link_path) and not self.fs.list_dir(link_path):
                    self.fs.remove(link_path)
                else:
                    bak_path = f"{link_path}.bak"
                    idx = 1
                    while self.fs.exists(bak_path):
                        bak_path = f"{link_path}.bak.{idx}"
                        idx += 1
                    self.fs.rename(link_path, bak_path)
            self.fs.symlink(host_dir, link_path)
            mapped.append(folder)

        # Convenience My Documents -> host Documents
        my_docs = f"{user_root}/My Documents"
        if not self.fs.exists(my_docs) and not self.fs.is_symlink(my_docs):
            self.fs.symlink(f"{host_home}/Documents", my_docs)
        return mapped

    def ensure_prefix(self, prefix: str | None = None, *, wine_bin: str | None = None) -> dict[str, Any]:
        """Initialize a Wine64 prefix with DXVK 1.10.3 DLLs, registry overrides, and ~/ symlinks."""
        target = (prefix or self.config.wine_prefix).replace("\\", "/")
        self.fs.mkdir(target, parents=True)
        runtime = self.selector.select_runtime(preferred=wine_bin)
        env, _ = self.build_env(prefix=target)

        system_reg = f"{target}/system.reg"
        if not self.fs.exists(system_reg):
            init_env = dict(env)
            init_env["WINEDLLOVERRIDES"] = "mscoree,mshtml="
            self.runner.run([runtime.binary, "wineboot", "--init"], env=init_env, check=True)
            self.runner.run([runtime.wineserver, "-w"], env=init_env, check=False)

        # Apply DLL overrides & WineD3D GL renderer registry settings
        reg_cmds = [
            ["reg", "add", r"HKCU\Software\Wine\Direct3D", "/v", "renderer", "/t", "REG_SZ", "/d", "gl", "/f"],
            *[
                ["reg", "add", r"HKCU\Software\Wine\DllOverrides", "/v", dll, "/t", "REG_SZ", "/d", "native,builtin", "/f"]
                for dll in DXVK_DLL_NAMES
            ],
            ["reg", "add", r"HKCU\Software\Wine\DllOverrides", "/v", "d3d12", "/t", "REG_SZ", "/d", "builtin", "/f"],
            ["reg", "add", r"HKCU\Software\Wine\DllOverrides", "/v", "d3d12core", "/t", "REG_SZ", "/d", "builtin", "/f"],
        ]
        for args in reg_cmds:
            self.runner.run([runtime.binary, *args], env=env, check=False)

        # Copy DXVK 1.10.3 DLLs if provisioned locally
        dll_hashes: dict[str, str] = {}
        dxvk_root = self.config.wine_dxvk_dir
        for src_arch, dst_arch in (("x64", "drive_c/windows/system32"), ("x32", "drive_c/windows/syswow64")):
            dst_dir = f"{target}/{dst_arch}"
            self.fs.mkdir(dst_dir, parents=True)
            for dll in DXVK_DLL_NAMES:
                src_file = f"{dxvk_root}/{src_arch}/{dll}.dll"
                if self.fs.exists(src_file):
                    raw = self.fs.read_bytes(src_file)
                    rel_dst = f"{dst_arch}/{dll}.dll"
                    self.fs.write_bytes(f"{target}/{rel_dst}", raw)
                    dll_hashes[rel_dst] = hashlib.sha256(raw).hexdigest()

        mapped = self.map_user_folders(target)
        manifest = {
            "schema_version": 1,
            "dxvk_version": REQUIRED_DXVK_VERSION,
            "wined3d_dx12": True,
            "ntsync_checked": self.check_ntsync(),
            "mapped_folders": mapped,
            "dll_sha256": dll_hashes,
        }
        self.fs.write_text(f"{target}/.kitebridge-manifest.json", json.dumps(manifest, indent=2) + "\n")
        return manifest

    def plan_launch(
        self,
        target_path: str,
        *,
        args: Sequence[str] = (),
        prefix: str | None = None,
        wine_bin: str | None = None,
        base_env: Mapping[str, str] | None = None,
        profile: HwProfile | None = None,
        silent: bool = False,
        allow_virtual: bool = True,
        detection_method: str = "extension",
        extension_override: str | None = None,
    ) -> RouteDecision:
        """Build a RouteDecision (Contract #7) for .exe/.msi/.bat/.cmd/.lnk."""
        target_prefix = (prefix or self.config.wine_prefix).replace("\\", "/")
        active_profile = profile or self.hw_reader.read(self.config.hw_profile_path)
        env, warnings = self.build_env(prefix=target_prefix, base_env=base_env, profile=active_profile)

        if self.fs.exists(target_prefix):
            warnings.extend(self.verify_prefix(target_prefix))

        runtime = self.selector.select_runtime(preferred=wine_bin, env=base_env, allow_virtual=allow_virtual)
        ext = extension_override or PurePosixPath(target_path.replace("\\", "/")).suffix.lower() or ".exe"
        extra_args = list(args)
        metadata: dict[str, Any] = {
            "wine_flavor": runtime.flavor,
            "ntsync": self.check_ntsync(),
            "prefix": target_prefix,
        }

        if ext == ".msi":
            cmd = [runtime.binary, "msiexec", "/i", target_path]
            if silent:
                cmd.append("/qn")
            cmd.extend(extra_args)
            mime_type = "application/x-msi"
        elif ext in (".bat", ".cmd"):
            cmd = [runtime.binary, "cmd", "/c", target_path, *extra_args]
            mime_type = "application/x-bat"
        elif ext == ".lnk":
            mime_type = "application/x-ms-shortcut"
            parsed = None
            if self.fs.exists(target_path):
                parsed = parse_lnk(self.fs.read_bytes(target_path), prefix_path=target_prefix)
            if parsed and parsed.target_posix_path:
                resolved = parsed.target_posix_path
                metadata["lnk_target"] = resolved
                metadata["lnk_working_dir"] = parsed.working_dir
                resolved_ext = PurePosixPath(resolved).suffix.lower()
                lnk_args = parsed.arguments.split() if parsed.arguments else []
                if resolved_ext == ".msi":
                    cmd = [runtime.binary, "msiexec", "/i", resolved, *lnk_args, *extra_args]
                elif resolved_ext in (".bat", ".cmd"):
                    cmd = [runtime.binary, "cmd", "/c", resolved, *lnk_args, *extra_args]
                else:
                    cmd = [runtime.binary, resolved, *lnk_args, *extra_args]
            else:
                cmd = [runtime.binary, "start", "/unix", target_path, *extra_args]
        else:
            cmd = [runtime.binary, target_path, *extra_args]
            mime_type = "application/x-ms-dos-executable"

        return RouteDecision(
            path=target_path,
            extension=ext,
            platform=Platform.WIN,
            handler="wine-ntsync",
            mime_type=mime_type,
            detection_method=detection_method,  # type: ignore[arg-type]
            dxvk_version=REQUIRED_DXVK_VERSION,
            wined3d_dx12=True,
            command=cmd,
            env=env,
            tier_mode=active_profile.tier,
            warnings=warnings,
            metadata=metadata,
        )

    def launch(
        self,
        target_path: str,
        *,
        args: Sequence[str] = (),
        prefix: str | None = None,
        wine_bin: str | None = None,
        dry_run: bool = False,
        silent: bool = False,
        extension_override: str | None = None,
        profile: HwProfile | None = None,
        hw_profile_path: str | None = None,
    ) -> tuple[RouteDecision, CommandResult | None]:
        active_profile = profile or (
            self.hw_reader.read(hw_profile_path) if hw_profile_path else None
        )
        decision = self.plan_launch(
            target_path,
            args=args,
            prefix=prefix,
            wine_bin=wine_bin,
            profile=active_profile,
            silent=silent,
            allow_virtual=dry_run,
            extension_override=extension_override,
        )
        if dry_run:
            return decision, None
        result = self.runner.run(decision.command, env=decision.env)
        return decision, result
