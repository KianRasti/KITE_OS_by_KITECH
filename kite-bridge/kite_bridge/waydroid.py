"""Android subsystem: Waydroid multi-window Wayland, APK/AAB, and RAM-tier cgroup v2 lifecycle."""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import time
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable, Literal, Mapping, Sequence

from . import LIBVA_DRIVER_PIN, MESA_DRIVER_PIN
from .abstractions import (
    CgroupController,
    CgroupV2Controller,
    HwProfileReader,
    LocalPrefixFilesystem,
    PosixSystemProbe,
    PrefixFilesystem,
    ProcessRunner,
    SubprocessRunner,
    SystemProbe,
)
from .config import BridgeConfig, haswell_base_env
from .fakes import TempPrefixFilesystem
from .hw_profile import JsonHwProfileReader
from .models import (
    CommandResult,
    HwProfile,
    MissingToolError,
    Platform,
    RouteDecision,
    WaydroidState,
)

ArmTranslation = Literal["libndk", "libhoudini", "none"]
_PKG_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+$")


@dataclass(frozen=True)
class WaydroidPrereqs:
    binder_available: bool
    psi_available: bool
    multi_windows_enabled: bool
    arm_translation: ArmTranslation
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApkInspectInfo:
    path: str
    kind: Literal["apk", "aab"]
    package_name: str | None
    abis: tuple[str, ...]
    has_manifest: bool


def extract_axml_strings(data: bytes) -> list[str]:
    """Lightweight pure-Python Android binary XML (AXML) string pool extractor."""
    if len(data) < 8:
        return []
    magic = struct.unpack_from("<I", data, 0)[0]
    # Standard AXML chunk header: 0x00080003 (RES_XML_TYPE + header_size=8)
    if (magic & 0xFFFF) != 0x0003:
        return []

    pos = 8
    strings: list[str] = []
    while pos + 8 <= len(data):
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, pos)
        if chunk_size < 8 or pos + chunk_size > len(data):
            break
        if chunk_type == 0x0001 and chunk_size >= 28:  # RES_STRING_POOL_TYPE
            string_count, _style_count, flags, strings_start, _styles_start = struct.unpack_from(
                "<IIIII", data, pos + 8
            )
            is_utf8 = bool(flags & (1 << 8))
            offsets_base = pos + header_size
            pool_base = pos + strings_start
            for i in range(string_count):
                off_pos = offsets_base + i * 4
                if off_pos + 4 > pos + chunk_size:
                    break
                str_rel = struct.unpack_from("<I", data, off_pos)[0]
                s_pos = pool_base + str_rel
                if s_pos >= pos + chunk_size:
                    continue
                if is_utf8:
                    # Skip u16len & u8len (1 or 2 bytes each)
                    if s_pos + 2 >= pos + chunk_size:
                        continue
                    b0 = data[s_pos]
                    s_pos += 2 if (b0 & 0x80) else 1
                    if s_pos >= pos + chunk_size:
                        continue
                    b1 = data[s_pos]
                    if b1 & 0x80:
                        if s_pos + 1 >= pos + chunk_size:
                            continue
                        byte_len = ((b1 & 0x7F) << 8) | data[s_pos + 1]
                        s_pos += 2
                    else:
                        byte_len = b1
                        s_pos += 1
                    raw = data[s_pos:s_pos + byte_len]
                    strings.append(raw.decode("utf-8", errors="replace"))
                else:
                    if s_pos + 2 > pos + chunk_size:
                        continue
                    char_len = struct.unpack_from("<H", data, s_pos)[0]
                    s_pos += 2
                    if char_len & 0x8000:
                        if s_pos + 2 > pos + chunk_size:
                            continue
                        char_len = ((char_len & 0x7FFF) << 16) | struct.unpack_from("<H", data, s_pos)[0]
                        s_pos += 2
                    raw = data[s_pos:s_pos + char_len * 2]
                    strings.append(raw.decode("utf-16le", errors="replace"))
            break
        pos += chunk_size
    return strings


def _open_zip(filesystem: PrefixFilesystem, archive_path: str) -> zipfile.ZipFile:
    if isinstance(filesystem, LocalPrefixFilesystem):
        return zipfile.ZipFile(archive_path, "r")
    if isinstance(filesystem, TempPrefixFilesystem):
        return zipfile.ZipFile(filesystem._map(archive_path), "r")
    return zipfile.ZipFile(io.BytesIO(filesystem.read_bytes(archive_path)), "r")


def inspect_android_archive(
    archive_path: str,
    *,
    fs: PrefixFilesystem | None = None,
    runner: ProcessRunner | None = None,
) -> ApkInspectInfo:
    """Inspect an .apk or .aab archive offline using zipfile + pure-Python AXML + optional aapt2."""
    filesystem = fs or LocalPrefixFilesystem()
    ext = PurePosixPath(archive_path.replace("\\", "/")).suffix.lower()
    kind: Literal["apk", "aab"] = "aab" if ext == ".aab" else "apk"
    if not filesystem.exists(archive_path):
        return ApkInspectInfo(path=archive_path, kind=kind, package_name=None, abis=(), has_manifest=False)

    abis: set[str] = set()
    has_manifest = False
    package_name: str | None = None

    try:
        with _open_zip(filesystem, archive_path) as zf:
            names = zf.namelist()
            if "BundleConfig.pb" in names or "base/manifest/AndroidManifest.xml" in names:
                kind = "aab"
            manifest_entry = (
                "base/manifest/AndroidManifest.xml"
                if "base/manifest/AndroidManifest.xml" in names
                else "AndroidManifest.xml"
                if "AndroidManifest.xml" in names
                else None
            )
            has_manifest = manifest_entry is not None

            for name in names:
                parts = name.split("/")
                if len(parts) >= 3 and parts[0] == "lib":
                    abis.add(parts[1])
                elif len(parts) >= 4 and parts[0] == "base" and parts[1] == "lib":
                    abis.add(parts[2])

            if manifest_entry:
                manifest_bytes = zf.read(manifest_entry)
                axml_strings = extract_axml_strings(manifest_bytes)
                for cand in axml_strings:
                    if _PKG_NAME_RE.match(cand) and not cand.startswith("android.") and not cand.startswith("http"):
                        package_name = cand
                        break
    except zipfile.BadZipFile:
        return ApkInspectInfo(
            path=archive_path,
            kind=kind,
            package_name=None,
            abis=(),
            has_manifest=False,
        )

    if package_name is None and kind == "apk" and runner is not None:
        aapt2 = runner.which("aapt2")
        if aapt2:
            res = runner.run([aapt2, "dump", "badging", archive_path])
            m = re.search(r"package:\s+name='([^']+)'", res.stdout)
            if m:
                package_name = m.group(1)

    return ApkInspectInfo(
        path=archive_path,
        kind=kind,
        package_name=package_name,
        abis=tuple(sorted(abis)),
        has_manifest=has_manifest,
    )


class WaydroidLifecycleManager:
    """RAM-tier aware Waydroid lifecycle state machine (Contract #1)."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        cgroups: CgroupController | None = None,
        hw_reader: HwProfileReader | None = None,
        clock: Callable[[], float] | None = None,
        config: BridgeConfig | None = None,
        hw_profile_path: str | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs
        self.cgroups = cgroups or CgroupV2Controller()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self.hw_reader = hw_reader or JsonHwProfileReader(probe=self.probe)
        self.clock = clock or time.monotonic
        self.hw_profile_path = hw_profile_path
        self.state: WaydroidState = WaydroidState.STOPPED
        self.idle_since: float | None = None
        self.warnings: list[str] = []
        self._load_state()

    @property
    def state_path(self) -> str:
        return f"{self.config.data_dir}/waydroid/lifecycle-state.json"

    def _load_state(self) -> None:
        if self.fs is not None and self.fs.exists(self.state_path):
            try:
                raw = json.loads(self.fs.read_text(self.state_path))
                if isinstance(raw, dict):
                    state_val = raw.get("state", WaydroidState.STOPPED.value)
                    try:
                        self.state = WaydroidState(str(state_val))
                    except ValueError:
                        self.state = WaydroidState.STOPPED
                    idle_raw = raw.get("idle_since")
                    self.idle_since = float(idle_raw) if idle_raw is not None else None
            except (OSError, ValueError, TypeError):
                pass
        if self.cgroups.is_frozen("waydroid"):
            self.state = WaydroidState.FROZEN

    def _save_state(self) -> None:
        if self.fs is None:
            return
        payload = {
            "state": self.state.value,
            "idle_since": self.idle_since,
        }
        self.fs.write_text(self.state_path, json.dumps(payload, indent=2) + "\n")

    def current_profile(self, hw_profile_path: str | None = None) -> HwProfile:
        return self.hw_reader.read(hw_profile_path or self.hw_profile_path or self.config.hw_profile_path)

    def _waydroid_env(self) -> dict[str, str]:
        return haswell_base_env()

    def _start_session(self) -> None:
        env = self._waydroid_env()
        self.runner.run(["waydroid", "container", "start"], env=env, check=False)
        self.runner.run(["waydroid", "session", "start"], env=env, check=False)
        self.runner.run(["waydroid", "prop", "set", "persist.waydroid.multi_windows", "true"], env=env, check=False)
        self.state = WaydroidState.ACTIVE
        self.idle_since = None
        self._save_state()

    def _stop_session(self) -> None:
        env = self._waydroid_env()
        self.runner.run(["waydroid", "session", "stop"], env=env, check=False)
        self.runner.run(["waydroid", "container", "stop"], env=env, check=False)
        self.state = WaydroidState.STOPPED
        self.idle_since = None
        self._save_state()

    def prewarm(self, *, hw_profile_path: str | None = None) -> WaydroidState:
        profile = self.current_profile(hw_profile_path)
        if profile.waydroid_prewarm or profile.tier == "16G":
            if self.state == WaydroidState.STOPPED:
                self._start_session()
            elif self.state == WaydroidState.FROZEN:
                self.unfreeze()
        return self.state

    def ensure_active(self) -> WaydroidState:
        self.idle_since = None
        if self.state == WaydroidState.STOPPED:
            self._start_session()
        elif self.state == WaydroidState.FROZEN:
            self.unfreeze()
        else:
            self._save_state()
        return self.state

    def freeze(self) -> WaydroidState:
        if self.state == WaydroidState.STOPPED:
            return self.state
        if self.state == WaydroidState.FROZEN:
            return self.state
        try:
            self.cgroups.freeze("waydroid")
        except OSError as exc:
            self.warnings.append(f"cgroup.freeze unavailable: {exc}")
        self.state = WaydroidState.FROZEN
        self._save_state()
        return self.state

    def unfreeze(self) -> WaydroidState:
        if self.state == WaydroidState.FROZEN:
            try:
                self.cgroups.thaw("waydroid")
            except OSError as exc:
                self.warnings.append(f"cgroup.thaw unavailable: {exc}")
            self.state = WaydroidState.ACTIVE
        self.idle_since = None
        self._save_state()
        return self.state

    def teardown(self) -> WaydroidState:
        if self.state != WaydroidState.STOPPED:
            if self.state == WaydroidState.FROZEN:
                try:
                    self.cgroups.thaw("waydroid")
                except OSError:
                    pass
            self._stop_session()
        return self.state

    def on_idle(self, now: float | None = None, *, hw_profile_path: str | None = None) -> WaydroidState:
        ts = self.clock() if now is None else now
        profile = self.current_profile(hw_profile_path)
        if profile.waydroid_idle_policy == "prewarmed" or profile.tier == "16G":
            if self.state == WaydroidState.FROZEN:
                self.unfreeze()
            return self.state

        if self.state == WaydroidState.STOPPED:
            return self.state

        if self.idle_since is None:
            self.idle_since = ts

        if self.state == WaydroidState.ACTIVE:
            self.freeze()
        else:
            self._save_state()
        return self.state

    def tick(self, now: float | None = None, *, hw_profile_path: str | None = None) -> WaydroidState:
        ts = self.clock() if now is None else now
        profile = self.current_profile(hw_profile_path)
        if profile.waydroid_idle_policy == "prewarmed" or profile.tier == "16G":
            return self.state

        if (
            profile.waydroid_idle_policy == "freeze_then_teardown"
            and profile.waydroid_teardown_after_sec is not None
            and self.state == WaydroidState.FROZEN
            and self.idle_since is not None
            and (ts - self.idle_since) >= profile.waydroid_teardown_after_sec
        ):
            self.teardown()
        return self.state

    def status_dict(self, *, hw_profile_path: str | None = None) -> dict[str, Any]:
        profile = self.current_profile(hw_profile_path)
        return {
            "state": self.state.value,
            "tier": profile.tier,
            "idle_policy": profile.waydroid_idle_policy,
            "teardown_after_sec": profile.waydroid_teardown_after_sec,
            "prewarm": profile.waydroid_prewarm,
            "idle_since": self.idle_since,
            "cgroup_frozen": self.cgroups.is_frozen("waydroid"),
            "warnings": list(self.warnings),
        }


class WaydroidSubsystem:
    """Android app installation (.apk/.aab), Wayland multi-window props, and lifecycle bridge."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        cgroups: CgroupController | None = None,
        hw_reader: HwProfileReader | None = None,
        clock: Callable[[], float] | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self.hw_reader = hw_reader or JsonHwProfileReader(probe=self.probe)
        self.lifecycle = WaydroidLifecycleManager(
            runner=self.runner,
            probe=self.probe,
            fs=self.fs,
            cgroups=cgroups,
            hw_reader=self.hw_reader,
            clock=clock,
            config=self.config,
        )

    def check_prerequisites(self) -> WaydroidPrereqs:
        warnings: list[str] = []
        binder_ok = bool(self.probe.glob("/dev/binder*")) or self.probe.exists("/dev/binderfs/binder")
        if not binder_ok:
            warnings.append("No /dev/binder* or /dev/binderfs/binder device detected (binder_linux required).")

        psi_ok = self.probe.exists("/proc/pressure/memory") and self.probe.exists("/proc/pressure/cpu")
        if not psi_ok:
            warnings.append("Kernel PSI (/proc/pressure/memory, /proc/pressure/cpu) not enabled (boot with psi=1).")

        props = self._read_props()
        multi_win = props.get("persist.waydroid.multi_windows", "").lower() == "true"
        arm = self.detect_arm_translation(props)
        return WaydroidPrereqs(
            binder_available=binder_ok,
            psi_available=psi_ok,
            multi_windows_enabled=multi_win,
            arm_translation=arm,
            warnings=tuple(warnings),
        )

    def _read_props(self) -> dict[str, str]:
        props: dict[str, str] = {}
        prop_path = self.config.waydroid_prop_path
        if self.fs.exists(prop_path):
            for line in self.fs.read_text(prop_path).splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        return props

    def detect_arm_translation(self, props: Mapping[str, str] | None = None) -> ArmTranslation:
        mapping = props if props is not None else self._read_props()
        bridge = mapping.get("ro.dalvik.vm.native.bridge", "")
        if "libndk_translation" in bridge:
            return "libndk"
        if "libhoudini" in bridge:
            return "libhoudini"
        if self.probe.exists(f"{self.config.waydroid_overlay_dir}/system/lib64/libndk_translation.so"):
            return "libndk"
        if self.probe.exists(f"{self.config.waydroid_overlay_dir}/system/lib64/libhoudini.so"):
            return "libhoudini"
        return "libndk"

    def configure_properties(self, *, arm_translation: ArmTranslation = "libndk") -> dict[str, str]:
        props = self._read_props()
        props["persist.waydroid.multi_windows"] = "true"
        props["ro.hardware.egl"] = "mesa"
        props["ro.hardware.gralloc"] = "gbm"
        if arm_translation != "none":
            so_name = "libndk_translation.so" if arm_translation == "libndk" else "libhoudini.so"
            props["ro.dalvik.vm.isa.arm"] = "x86"
            props["ro.dalvik.vm.isa.arm64"] = "x86_64"
            props["ro.enable.native.bridge.exec"] = "1"
            props["ro.dalvik.vm.native.bridge"] = so_name
            props["ro.product.cpu.abilist"] = "x86_64,x86,arm64-v8a,armeabi-v7a,armeabi"
            props["ro.product.cpu.abilist64"] = "x86_64,arm64-v8a"
            props["ro.product.cpu.abilist32"] = "x86,armeabi-v7a,armeabi"

        rendered = "\n".join(f"{k}={v}" for k, v in sorted(props.items())) + "\n"
        self.fs.write_text(self.config.waydroid_prop_path, rendered)
        return props

    def _bundletool_cmd(self) -> list[str]:
        bt = self.runner.which("bundletool")
        if bt:
            return [bt]
        jar = f"{self.config.data_dir}/waydroid/tools/bundletool-all.jar"
        if self.fs.exists(jar) or self.probe.exists(jar):
            return ["java", "-jar", jar]
        return ["bundletool"]

    def _aab_cache_dir(self, aab_path: str) -> str:
        digest = hashlib.sha256(aab_path.encode("utf-8")).hexdigest()[:16]
        return f"{self.config.data_dir}/waydroid/aab-cache/{digest}"

    def plan_launch(
        self,
        target_path: str,
        *,
        profile: HwProfile | None = None,
        detection_method: str = "extension",
        package_name: str | None = None,
    ) -> RouteDecision:
        active_profile = profile or self.hw_reader.read(self.config.hw_profile_path)
        prereqs = self.check_prerequisites()
        info = inspect_android_archive(target_path, fs=self.fs, runner=self.runner)
        pkg = package_name or info.package_name
        env = haswell_base_env()
        warnings = list(prereqs.warnings)

        if info.kind == "aab":
            cache_dir = self._aab_cache_dir(target_path)
            apks_out = f"{cache_dir}/bundle.apks"
            universal_apk = f"{cache_dir}/universal.apk"
            bt_cmd = self._bundletool_cmd()
            build_cmd = [
                *bt_cmd,
                "build-apks",
                f"--bundle={target_path}",
                f"--output={apks_out}",
                "--mode=universal",
            ]
            command = ["waydroid", "app", "install", universal_apk]
            mime_type = "application/vnd.android.aab"
            ext = ".aab"
            metadata: dict[str, Any] = {
                "multi_windows": True,
                "persist.waydroid.multi_windows": True,
                "arm_translation": prereqs.arm_translation,
                "lifecycle_policy": active_profile.waydroid_idle_policy,
                "package_name": pkg,
                "abis": list(info.abis),
                "bundletool_command": build_cmd,
                "universal_apk": universal_apk,
            }
        else:
            command = ["waydroid", "app", "install", target_path]
            mime_type = "application/vnd.android.package-archive"
            ext = ".apk"
            metadata = {
                "multi_windows": True,
                "persist.waydroid.multi_windows": True,
                "arm_translation": prereqs.arm_translation,
                "lifecycle_policy": active_profile.waydroid_idle_policy,
                "package_name": pkg,
                "abis": list(info.abis),
            }

        return RouteDecision(
            path=target_path,
            extension=ext,
            platform=Platform.ANDROID,
            handler="waydroid-multiwindow",
            mime_type=mime_type,
            detection_method=detection_method,  # type: ignore[arg-type]
            dxvk_version=None,
            wined3d_dx12=False,
            command=command,
            env=env,
            tier_mode=active_profile.tier,
            warnings=warnings,
            metadata=metadata,
        )

    def install_and_launch(
        self,
        target_path: str,
        *,
        dry_run: bool = False,
        package_name: str | None = None,
        profile: HwProfile | None = None,
        hw_profile_path: str | None = None,
    ) -> tuple[RouteDecision, list[CommandResult]]:
        active_profile = profile or (
            self.hw_reader.read(hw_profile_path) if hw_profile_path else None
        )
        decision = self.plan_launch(
            target_path,
            profile=active_profile,
            package_name=package_name,
        )
        if dry_run:
            return decision, []

        if hw_profile_path:
            self.lifecycle.hw_profile_path = hw_profile_path
        results: list[CommandResult] = []
        self.lifecycle.ensure_active()
        self.runner.run(
            ["waydroid", "prop", "set", "persist.waydroid.multi_windows", "true"],
            env=decision.env,
            check=False,
        )

        if decision.extension == ".aab":
            bt_cmd = decision.metadata["bundletool_command"]
            bt_bin = bt_cmd[0]
            if bt_bin == "bundletool" and not self.runner.which("bundletool"):
                raise MissingToolError("bundletool", "Run `scripts/provision-waydroid.sh` to install bundletool.")
            cache_dir = str(PurePosixPath(decision.metadata["universal_apk"]).parent)
            self.fs.mkdir(cache_dir, parents=True)
            bt_res = self.runner.run(bt_cmd, env=decision.env, check=True)
            results.append(bt_res)
            apks_path = f"{cache_dir}/bundle.apks"
            if self.fs.exists(apks_path):
                with zipfile.ZipFile(io.BytesIO(self.fs.read_bytes(apks_path)), "r") as zf:
                    if "universal.apk" in zf.namelist():
                        self.fs.write_bytes(decision.metadata["universal_apk"], zf.read("universal.apk"))

        inst_res = self.runner.run(decision.command, env=decision.env, check=True)
        results.append(inst_res)
        pkg = decision.metadata.get("package_name")
        if pkg:
            launch_res = self.runner.run(["waydroid", "app", "launch", str(pkg)], env=decision.env, check=False)
            results.append(launch_res)
        return decision, results
