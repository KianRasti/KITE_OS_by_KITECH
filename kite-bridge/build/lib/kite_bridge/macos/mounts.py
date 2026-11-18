"""Native macOS volume mounting: darling-dmg, hfsprogs, and apfs-fuse."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Iterator, Literal

from ..abstractions import (
    LocalPrefixFilesystem,
    PosixSystemProbe,
    PrefixFilesystem,
    ProcessRunner,
    SubprocessRunner,
    SystemProbe,
)
from ..config import BridgeConfig
from ..models import BridgeError, MissingToolError, MountRecord

ImageKind = Literal["dmg", "apfs", "hfsplus"]


def detect_image_kind(
    source_path: str,
    *,
    probe: SystemProbe | None = None,
    fs: PrefixFilesystem | None = None,
) -> ImageKind:
    """Detect macOS disk image type via bounded header/trailer magic bytes or extension."""
    ext = PurePosixPath(source_path.replace("\\", "/")).suffix.lower()
    head_bytes = b""
    tail_bytes = b""
    total_size = 0
    have_bytes = False

    if fs is not None and fs.exists(source_path):
        try:
            head_bytes, tail_bytes, total_size = fs.read_head_tail(source_path, head=2048, tail=512)
            have_bytes = True
        except OSError:
            have_bytes = False
    elif probe is not None and probe.exists(source_path):
        try:
            head_bytes, tail_bytes, total_size = probe.read_head_tail(source_path, head=2048, tail=512)
            have_bytes = True
        except OSError:
            have_bytes = False

    if have_bytes:
        if total_size >= 512 and len(tail_bytes) >= 512 and tail_bytes[-512:-508] == b"koly":
            return "dmg"
        if len(head_bytes) >= 36 and head_bytes[0x20:0x24] == b"NXSB":
            return "apfs"
        if len(head_bytes) >= 1026 and head_bytes[1024:1026] in (b"H+", b"HX"):
            return "hfsplus"

    if ext in (".apfs",):
        return "apfs"
    if ext in (".hfs", ".hfsplus"):
        return "hfsplus"
    return "dmg"


class MacMountManager:
    """Manages read-only/loop mounts for .dmg, HFS+, and APFS volumes."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self._mounts: dict[str, MountRecord] = {}

    def default_mountpoint(self, source_path: str) -> str:
        p = PurePosixPath(source_path.replace("\\", "/"))
        slug = "".join(ch if ch.isalnum() else "-" for ch in p.stem.lower()).strip("-") or "volume"
        digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:8]
        return f"{self.config.macos_dir}/mounts/{slug}-{digest}"

    def _require_tool(self, tool: str, hint: str) -> str:
        resolved = self.runner.which(tool)
        if not resolved:
            raise MissingToolError(tool, hint)
        return resolved

    def mount_dmg(self, image_path: str, mountpoint: str | None = None) -> MountRecord:
        target_mnt = mountpoint or self.default_mountpoint(image_path)
        if target_mnt in self._mounts:
            return self._mounts[target_mnt]
        tool = self._require_tool("darling-dmg", "Run `scripts/provision-macos.sh` or install darling-dmg.")
        if not (self.fs.exists(image_path) or self.probe.exists(image_path)):
            raise BridgeError(f"DMG image not found: {image_path}")
        self.fs.mkdir(target_mnt, parents=True)
        res = self.runner.run([tool, image_path, target_mnt])
        if res.returncode != 0:
            raise BridgeError(f"darling-dmg failed ({res.returncode}): {res.stderr}")
        rec = MountRecord(source_path=image_path, mountpoint=target_mnt, fs_type="dmg", read_only=True, fuse=True)
        self._mounts[target_mnt] = rec
        return rec

    def mount_hfsplus(
        self,
        source_path: str,
        mountpoint: str | None = None,
        *,
        read_only: bool = True,
        fsck: bool = True,
        strict_fsck: bool = False,
    ) -> MountRecord:
        target_mnt = mountpoint or self.default_mountpoint(source_path)
        if target_mnt in self._mounts:
            return self._mounts[target_mnt]
        self.fs.mkdir(target_mnt, parents=True)

        if fsck:
            fsck_bin = self._require_tool("fsck.hfsplus", "Install `hfsprogs` for HFS+ volume checks.")
            fsck_res = self.runner.run([fsck_bin, "-n", source_path])
            if strict_fsck and fsck_res.returncode != 0:
                raise BridgeError(f"fsck.hfsplus failed ({fsck_res.returncode}): {fsck_res.stderr}")

        mount_bin = self.runner.which("mount") or "mount"
        is_block_dev = source_path.startswith("/dev/")
        mode = "ro" if read_only else "rw"
        opts = mode if is_block_dev else f"{mode},loop"
        res = self.runner.run([mount_bin, "-t", "hfsplus", "-o", opts, source_path, target_mnt])
        if res.returncode != 0:
            raise BridgeError(f"mount -t hfsplus failed ({res.returncode}): {res.stderr}")
        rec = MountRecord(
            source_path=source_path,
            mountpoint=target_mnt,
            fs_type="hfsplus",
            read_only=read_only,
            fuse=False,
        )
        self._mounts[target_mnt] = rec
        return rec

    def mount_apfs(
        self,
        source_path: str,
        mountpoint: str | None = None,
        *,
        read_only: bool = True,
        allow_other: bool = True,
    ) -> MountRecord:
        target_mnt = mountpoint or self.default_mountpoint(source_path)
        if target_mnt in self._mounts:
            return self._mounts[target_mnt]
        tool = self._require_tool("apfs-fuse", "Run `scripts/provision-macos.sh` or install apfs-fuse.")
        self.fs.mkdir(target_mnt, parents=True)
        opts = "ro,allow_other" if (read_only and allow_other) else ("ro" if read_only else "rw")
        res = self.runner.run([tool, "-o", opts, source_path, target_mnt])
        if res.returncode != 0:
            raise BridgeError(f"apfs-fuse failed ({res.returncode}): {res.stderr}")
        rec = MountRecord(
            source_path=source_path,
            mountpoint=target_mnt,
            fs_type="apfs",
            read_only=read_only,
            fuse=True,
        )
        self._mounts[target_mnt] = rec
        return rec

    def unmount(self, mountpoint: str) -> None:
        rec = self._mounts.get(mountpoint)
        is_fuse = rec.fuse if rec is not None else True
        if is_fuse:
            for candidate in ("fusermount3", "fusermount", "umount"):
                tool = self.runner.which(candidate)
                if tool:
                    args = [tool, "-u", mountpoint] if "fusermount" in candidate else [tool, mountpoint]
                    res = self.runner.run(args)
                    if res.returncode == 0:
                        self._mounts.pop(mountpoint, None)
                        return
                    raise BridgeError(f"{candidate} unmount failed ({res.returncode}): {res.stderr}")
            # Fallback if no binary explicitly mocked
            res = self.runner.run(["umount", mountpoint])
            if res.returncode != 0:
                raise BridgeError(f"umount failed ({res.returncode}): {res.stderr}")
        else:
            umount_bin = self.runner.which("umount") or "umount"
            res = self.runner.run([umount_bin, mountpoint])
            if res.returncode != 0:
                raise BridgeError(f"umount failed ({res.returncode}): {res.stderr}")
        self._mounts.pop(mountpoint, None)

    def is_mounted(self, mountpoint: str) -> bool:
        return mountpoint in self._mounts

    def list_mounts(self) -> list[MountRecord]:
        return list(self._mounts.values())

    @contextmanager
    def mounted_volume(
        self,
        source_path: str,
        *,
        mountpoint: str | None = None,
        kind: ImageKind | None = None,
    ) -> Iterator[MountRecord]:
        resolved_kind = kind or detect_image_kind(source_path, probe=self.probe, fs=self.fs)
        if resolved_kind == "dmg":
            rec = self.mount_dmg(source_path, mountpoint)
        elif resolved_kind == "apfs":
            rec = self.mount_apfs(source_path, mountpoint)
        else:
            rec = self.mount_hfsplus(source_path, mountpoint)
        try:
            yield rec
        finally:
            if self.is_mounted(rec.mountpoint):
                self.unmount(rec.mountpoint)
