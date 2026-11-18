"""Unified MIME, magic-byte, and extension router for KiteBridge."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import PurePosixPath
from typing import Any, Literal

from .abstractions import (
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
from .macos.bundle import MACHO_MAGICS, AppBundleParser
from .macos.darling import DarlingRunner
from .macos.mounts import MacMountManager
from .macos.osx_kvm import REQUIRED_HASWELL_CPU_ARG, OsxKvmBridge
from .macos.packages import PkgHandler
from .models import HwProfile, KvmUnavailableError, Platform, RouteDecision
from .waydroid import WaydroidSubsystem
from .wine import WineSubsystem

_OLE2_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
_LNK_MAGIC = b"\x4C\x00\x00\x00\x01\x14\x02\x00"


class MimeRouter:
    """Classifies files and .app bundles via directory/magic-byte/extension inspection."""

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

        self.wine = WineSubsystem(
            runner=self.runner, probe=self.probe, fs=self.fs, hw_reader=self.hw_reader, config=self.config
        )
        self.waydroid = WaydroidSubsystem(
            runner=self.runner, probe=self.probe, fs=self.fs, hw_reader=self.hw_reader, config=self.config
        )
        self.darling = DarlingRunner(
            runner=self.runner, probe=self.probe, fs=self.fs, config=self.config
        )
        self.osx_kvm = OsxKvmBridge(
            runner=self.runner, probe=self.probe, fs=self.fs, hw_reader=self.hw_reader, config=self.config
        )
        self.mounts = MacMountManager(
            runner=self.runner, probe=self.probe, fs=self.fs, config=self.config
        )
        self.pkg_handler = PkgHandler(runner=self.runner, fs=self.fs, config=self.config)
        self.bundle_parser = AppBundleParser(fs=self.fs)

    def inspect(
        self,
        path: str,
        *,
        mode: Literal["auto", "cli", "gui"] = "auto",
        prefix: str | None = None,
        hw_profile_path: str | None = None,
        profile: HwProfile | None = None,
    ) -> RouteDecision:
        active_profile = profile or self.hw_reader.read(hw_profile_path or self.config.hw_profile_path)
        norm = path.replace("\\", "/")
        clean_no_slash = norm.rstrip("/")
        ext = PurePosixPath(clean_no_slash).suffix.lower()

        # 1. macOS .app bundle directory check
        if clean_no_slash.lower().endswith(".app"):
            return self._route_app_bundle(
                clean_no_slash,
                mode=mode,
                profile=active_profile,
            )

        # 2. Bounded magic-byte inspection on existing files (never reads multi-GB images into RAM)
        if self.fs.exists(path) and not self.fs.is_dir(path):
            head_bytes, tail_bytes, total_size = self.fs.read_head_tail(path, head=4096, tail=512)
            magic_decision = self._route_by_magic(
                path,
                ext=ext,
                head_bytes=head_bytes,
                tail_bytes=tail_bytes,
                total_size=total_size,
                mode=mode,
                prefix=prefix,
                profile=active_profile,
            )
            if magic_decision is not None:
                return magic_decision

        # 3. Extension fallback (synthetic paths or text scripts like .bat/.cmd)
        return self._route_by_extension(
            path,
            ext=ext,
            mode=mode,
            prefix=prefix,
            profile=active_profile,
        )

    def _route_app_bundle(
        self,
        app_path: str,
        *,
        mode: Literal["auto", "cli", "gui"],
        profile: HwProfile,
    ) -> RouteDecision:
        plist_exists = self.fs.exists(f"{app_path}/Contents/Info.plist")
        detection = "bundle" if plist_exists else "extension"
        metadata: dict[str, Any] = {}
        tier: Literal["darling", "osx_kvm"] = "darling" if mode == "cli" else "osx_kvm"
        app_target = app_path

        if plist_exists:
            info = self.bundle_parser.parse(app_path, require_executable=False, mode=mode)
            tier = info.tier
            app_target = info.bundle_name
            metadata = {
                "bundle_name": info.bundle_name,
                "bundle_identifier": info.bundle_identifier,
                "executable_path": info.executable_path,
                "icon_path": info.icon_path,
                "version": info.version,
                "is_binary_plist": info.is_binary_plist,
            }

        if tier == "darling":
            cmd = self.darling.build_command(app_path)
            env = self.darling.build_env()
            return RouteDecision(
                path=app_path,
                extension=".app",
                platform=Platform.MACOS,
                handler="darling-cli",
                mime_type="application/x-apple-app",
                detection_method=detection,  # type: ignore[arg-type]
                dxvk_version=None,
                wined3d_dx12=False,
                command=cmd,
                env=env,
                tier_mode=profile.tier,
                metadata=metadata,
            )

        return self._build_osx_kvm_decision(
            app_path,
            ext=".app",
            app_target=app_target,
            detection=detection,
            profile=profile,
            metadata=metadata,
        )

    def _build_osx_kvm_decision(
        self,
        path: str,
        *,
        ext: str,
        app_target: str,
        detection: str,
        profile: HwProfile,
        metadata: dict[str, Any] | None = None,
    ) -> RouteDecision:
        env = haswell_base_env()
        warnings: list[str] = []
        meta = dict(metadata or {})
        try:
            spec = self.osx_kvm.build_qemu_command(
                app_target=app_target,
                hw_profile=profile,
                allow_4g=True,
                require_preflight_tools=False,
            )
            cmd = spec.qemu_argv
            warnings.extend(spec.warnings)
            meta["virtiofsd_argv"] = spec.virtiofsd_argv
            meta["bridge_argv"] = spec.bridge_argv
            meta["hugepages_enabled"] = spec.hugepages_enabled
            meta["vm_ram_mb"] = spec.vm_ram_mb
            meta["window_forwarding"] = "vnc-127.0.0.1"
            meta["virtiofs_tag"] = "kite_home"
        except KvmUnavailableError as exc:
            warnings.append(str(exc))
            vm_ram = 2048 if profile.tier == "4G" else (6144 if profile.tier == "16G" else 4096)
            smp = "2,cores=2,threads=1,sockets=1" if profile.tier == "4G" else "4,cores=2,threads=2,sockets=1"
            cmd = [
                "qemu-system-x86_64",
                "-enable-kvm",
                "-machine",
                "q35,accel=kvm",
                "-cpu",
                REQUIRED_HASWELL_CPU_ARG,
                "-smp",
                smp,
                "-m",
                str(vm_ram),
                "-object",
                f"memory-backend-memfd,id=mem,size={vm_ram}M,share=on",
                "-numa",
                "node,memdev=mem",
                "-chardev",
                f"socket,id=char0,path={self.osx_kvm.virtiofs_socket}",
                "-device",
                "vhost-user-fs-pci,id=kite_home_fs,queue-size=1024,chardev=char0,tag=kite_home",
                "-vga",
                "std",
                "-display",
                "none",
                "-vnc",
                "127.0.0.1:0",
            ]
            meta["kvm_preflight_ready"] = False
            meta["vm_ram_mb"] = vm_ram
            meta["window_forwarding"] = "vnc-127.0.0.1"
            meta["virtiofs_tag"] = "kite_home"

        return RouteDecision(
            path=path,
            extension=ext,
            platform=Platform.MACOS,
            handler="osx-kvm-bridge",
            mime_type="application/x-apple-app",
            detection_method=detection,  # type: ignore[arg-type]
            dxvk_version=None,
            wined3d_dx12=False,
            command=cmd,
            env=env,
            tier_mode=profile.tier,
            warnings=warnings,
            metadata=meta,
        )

    def _open_zip_for_sniff(self, path: str) -> zipfile.ZipFile:
        if isinstance(self.fs, LocalPrefixFilesystem):
            return zipfile.ZipFile(path, "r")
        if isinstance(self.fs, TempPrefixFilesystem):
            return zipfile.ZipFile(self.fs._map(path), "r")
        return zipfile.ZipFile(io.BytesIO(self.fs.read_bytes(path)), "r")

    def _route_by_magic(
        self,
        path: str,
        *,
        ext: str,
        head_bytes: bytes,
        tail_bytes: bytes,
        total_size: int,
        mode: Literal["auto", "cli", "gui"],
        prefix: str | None,
        profile: HwProfile,
    ) -> RouteDecision | None:
        # 1. ZIP (APK or AAB)
        if head_bytes.startswith(b"PK\x03\x04"):
            try:
                with self._open_zip_for_sniff(path) as zf:
                    names = set(zf.namelist())
                    if "BundleConfig.pb" in names or "base/manifest/AndroidManifest.xml" in names:
                        return self.waydroid.plan_launch(
                            path,
                            profile=profile,
                            detection_method="magic+extension" if ext == ".aab" else "magic",
                        )
                    if "AndroidManifest.xml" in names:
                        return self.waydroid.plan_launch(
                            path,
                            profile=profile,
                            detection_method="magic+extension" if ext == ".apk" else "magic",
                        )
            except (zipfile.BadZipFile, OSError):
                pass

        # 2. PE executable (.exe)
        if len(head_bytes) >= 0x40 and head_bytes[:2] == b"MZ":
            pe_offset = struct.unpack_from("<I", head_bytes, 0x3C)[0]
            pe_hdr = head_bytes
            if pe_offset + 4 > len(pe_hdr) and pe_offset + 4 <= total_size and pe_offset < 65536:
                pe_hdr, _, _ = self.fs.read_head_tail(path, head=pe_offset + 4, tail=0)
            if pe_offset + 4 <= len(pe_hdr) and pe_hdr[pe_offset:pe_offset + 4] == b"PE\x00\x00":
                return self.wine.plan_launch(
                    path,
                    prefix=prefix,
                    profile=profile,
                    allow_virtual=True,
                    detection_method="magic+extension" if ext == ".exe" else "magic",
                    extension_override=".exe",
                )

        # 3. OLE2 MSI
        if head_bytes.startswith(_OLE2_MAGIC) and ext in (".msi", ""):
            return self.wine.plan_launch(
                path,
                prefix=prefix,
                profile=profile,
                allow_virtual=True,
                detection_method="magic+extension" if ext == ".msi" else "magic",
                extension_override=".msi",
            )

        # 4. Windows Shell Link (.lnk)
        if head_bytes.startswith(_LNK_MAGIC):
            return self.wine.plan_launch(
                path,
                prefix=prefix,
                profile=profile,
                allow_virtual=True,
                detection_method="magic+extension" if ext == ".lnk" else "magic",
                extension_override=".lnk",
            )

        # 5. Apple UDIF DMG ("koly" trailer in last 512 bytes)
        if total_size >= 512 and len(tail_bytes) >= 512 and tail_bytes[-512:-508] == b"koly":
            mnt = self.mounts.default_mountpoint(path)
            return RouteDecision(
                path=path,
                extension=ext or ".dmg",
                platform=Platform.MACOS,
                handler="darling-dmg",
                mime_type="application/x-apple-diskimage",
                detection_method="magic+extension" if ext == ".dmg" else "magic",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["darling-dmg", path, mnt],
                env=haswell_base_env(),
                tier_mode=profile.tier,
                metadata={"mountpoint": mnt},
            )

        # 6. Apple XAR .pkg
        if head_bytes.startswith(b"xar!"):
            return RouteDecision(
                path=path,
                extension=ext or ".pkg",
                platform=Platform.MACOS,
                handler="darling-pkg",
                mime_type="application/x-newton-compatible-pkg",
                detection_method="magic+extension" if ext == ".pkg" else "magic",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["darling", "shell", "installer", "-pkg", path, "-target", "/"],
                env=self.darling.build_env(),
                tier_mode=profile.tier,
            )

        # 7. APFS container ("NXSB" at offset 0x20)
        if len(head_bytes) >= 0x24 and head_bytes[0x20:0x24] == b"NXSB":
            mnt = self.mounts.default_mountpoint(path)
            return RouteDecision(
                path=path,
                extension=ext or ".apfs",
                platform=Platform.MACOS,
                handler="apfs-fuse",
                mime_type="application/x-apfs-image",
                detection_method="magic+extension" if ext == ".apfs" else "magic",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["apfs-fuse", "-o", "ro,allow_other", path, mnt],
                env=haswell_base_env(),
                tier_mode=profile.tier,
                metadata={"mountpoint": mnt},
            )

        # 8. HFS+ volume header ("H+" or "HX" at offset 1024)
        if len(head_bytes) >= 1026 and head_bytes[1024:1026] in (b"H+", b"HX"):
            mnt = self.mounts.default_mountpoint(path)
            return RouteDecision(
                path=path,
                extension=ext or ".hfs",
                platform=Platform.MACOS,
                handler="hfsprogs",
                mime_type="application/x-hfsplus-image",
                detection_method="magic+extension" if ext in (".hfs", ".hfsplus") else "magic",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["mount", "-t", "hfsplus", "-o", "ro,loop", path, mnt],
                env=haswell_base_env(),
                tier_mode=profile.tier,
                metadata={"mountpoint": mnt},
            )

        # 9. Standalone Mach-O CLI binary
        if len(head_bytes) >= 4:
            magic = struct.unpack_from(">I", head_bytes, 0)[0]
            if magic in MACHO_MAGICS:
                return RouteDecision(
                    path=path,
                    extension=ext,
                    platform=Platform.MACOS,
                    handler="darling-cli",
                    mime_type="application/x-mach-binary",
                    detection_method="magic",
                    dxvk_version=None,
                    wined3d_dx12=False,
                    command=self.darling.build_command(path),
                    env=self.darling.build_env(),
                    tier_mode=profile.tier,
                )

        return None

    def _route_by_extension(
        self,
        path: str,
        *,
        ext: str,
        mode: Literal["auto", "cli", "gui"],
        prefix: str | None,
        profile: HwProfile,
    ) -> RouteDecision:
        if ext in (".exe", ".msi", ".bat", ".cmd", ".lnk"):
            return self.wine.plan_launch(
                path,
                prefix=prefix,
                profile=profile,
                allow_virtual=True,
                detection_method="extension",
            )

        if ext in (".apk", ".aab"):
            return self.waydroid.plan_launch(
                path,
                profile=profile,
                detection_method="extension",
            )

        if ext == ".dmg":
            mnt = self.mounts.default_mountpoint(path)
            return RouteDecision(
                path=path,
                extension=ext,
                platform=Platform.MACOS,
                handler="darling-dmg",
                mime_type="application/x-apple-diskimage",
                detection_method="extension",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["darling-dmg", path, mnt],
                env=haswell_base_env(),
                tier_mode=profile.tier,
                metadata={"mountpoint": mnt},
            )

        if ext in (".pkg", ".mpkg"):
            return RouteDecision(
                path=path,
                extension=ext,
                platform=Platform.MACOS,
                handler="darling-pkg",
                mime_type="application/x-newton-compatible-pkg",
                detection_method="extension",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["darling", "shell", "installer", "-pkg", path, "-target", "/"],
                env=self.darling.build_env(),
                tier_mode=profile.tier,
            )

        if ext == ".apfs":
            mnt = self.mounts.default_mountpoint(path)
            return RouteDecision(
                path=path,
                extension=ext,
                platform=Platform.MACOS,
                handler="apfs-fuse",
                mime_type="application/x-apfs-image",
                detection_method="extension",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["apfs-fuse", "-o", "ro,allow_other", path, mnt],
                env=haswell_base_env(),
                tier_mode=profile.tier,
                metadata={"mountpoint": mnt},
            )

        if ext in (".hfs", ".hfsplus"):
            mnt = self.mounts.default_mountpoint(path)
            return RouteDecision(
                path=path,
                extension=ext,
                platform=Platform.MACOS,
                handler="hfsprogs",
                mime_type="application/x-hfsplus-image",
                detection_method="extension",
                dxvk_version=None,
                wined3d_dx12=False,
                command=["mount", "-t", "hfsplus", "-o", "ro,loop", path, mnt],
                env=haswell_base_env(),
                tier_mode=profile.tier,
                metadata={"mountpoint": mnt},
            )

        if ext == ".macho":
            return RouteDecision(
                path=path,
                extension=ext,
                platform=Platform.MACOS,
                handler="darling-cli",
                mime_type="application/x-mach-binary",
                detection_method="extension",
                dxvk_version=None,
                wined3d_dx12=False,
                command=self.darling.build_command(path),
                env=self.darling.build_env(),
                tier_mode=profile.tier,
            )

        return RouteDecision(
            path=path,
            extension=ext,
            platform=Platform.UNKNOWN,
            handler="unsupported",
            mime_type="application/octet-stream",
            detection_method="extension",
            dxvk_version=None,
            wined3d_dx12=False,
            command=[],
            env=haswell_base_env(),
            tier_mode=profile.tier,
            warnings=[f"Unsupported file extension '{ext or '<none>'}'."],
        )
