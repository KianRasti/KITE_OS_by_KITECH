"""Tests for macOS native volume mounting (darling-dmg, hfsprogs, apfs-fuse)."""

from __future__ import annotations

import pytest

from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.macos.mounts import MacMountManager, detect_image_kind
from kite_bridge.models import MissingToolError


def test_dmg_hfsplus_apfs_mounts_and_context_manager() -> None:
    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    runner = FakeProcessRunner(
        available_binaries={
            "darling-dmg": "/usr/bin/darling-dmg",
            "fsck.hfsplus": "/usr/bin/fsck.hfsplus",
            "mount": "/usr/bin/mount",
            "apfs-fuse": "/usr/bin/apfs-fuse",
            "fusermount3": "/usr/bin/fusermount3",
            "umount": "/usr/bin/umount",
        }
    )
    cfg = BridgeConfig.from_env(probe=probe, env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})
    mgr = MacMountManager(runner=runner, probe=probe, fs=fs, config=cfg)

    fs.write_bytes("/tmp/app.dmg", b"\x00" * 512 + b"koly" + b"\x00" * 508)
    assert detect_image_kind("/tmp/app.dmg", fs=fs) == "dmg"

    with pytest.raises(RuntimeError):
        with mgr.mounted_volume("/tmp/app.dmg") as rec:
            assert mgr.is_mounted(rec.mountpoint)
            raise RuntimeError("boom inside mount context")

    assert not mgr.is_mounted(rec.mountpoint)
    assert runner.invocations[0].argv[0] == "/usr/bin/darling-dmg"
    assert runner.invocations[1].argv[0] == "/usr/bin/fusermount3"

    # HFS+ image vs block device
    rec_hfs = mgr.mount_hfsplus("/tmp/disk.hfs", "/mnt/hfs")
    assert rec_hfs.fs_type == "hfsplus"
    assert any("ro,loop" in c.argv for c in runner.invocations)
    mgr.unmount("/mnt/hfs")

    mgr.mount_hfsplus("/dev/sdb2", "/mnt/hfs_dev")
    assert any(c.argv == ("/usr/bin/mount", "-t", "hfsplus", "-o", "ro", "/dev/sdb2", "/mnt/hfs_dev") for c in runner.invocations)

    # APFS
    rec_apfs = mgr.mount_apfs("/tmp/cont.apfs", "/mnt/apfs")
    assert rec_apfs.fs_type == "apfs"
    assert any(c.argv[0] == "/usr/bin/apfs-fuse" for c in runner.invocations)


def test_missing_mount_tool_raises_actionable_error() -> None:
    fs = InMemoryPrefixFilesystem()
    fs.write_bytes("/tmp/a.dmg", b"dmg")
    mgr = MacMountManager(runner=FakeProcessRunner(), probe=FakeSystemProbe(), fs=fs)
    with pytest.raises(MissingToolError):
        mgr.mount_dmg("/tmp/a.dmg")


def test_detect_image_kind_bounded_read_on_large_sparse_dmg(tmp_path) -> None:
    from kite_bridge.fakes import TempPrefixFilesystem

    class NoFullReadFs(TempPrefixFilesystem):
        def read_bytes(self, path: str) -> bytes:
            raise AssertionError("detect_image_kind must use read_head_tail, not read_bytes")

    fs = NoFullReadFs(tmp_path)
    img = tmp_path / "tmp" / "big.img"
    img.parent.mkdir(parents=True, exist_ok=True)
    with open(img, "wb") as fh:
        fh.seek(10 * 1024 * 1024 - 512)
        fh.write(b"koly" + b"\x00" * 508)

    assert detect_image_kind("/tmp/big.img", fs=fs) == "dmg"
