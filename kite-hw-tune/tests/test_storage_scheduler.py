"""Tests for rotational storage discovery and I/O scheduler selection."""

from __future__ import annotations

from pathlib import Path

from kite_hw_tune.abstractions import DirectorySysFs, FakeSysFs
from kite_hw_tune.storage import apply_storage_schedulers, detect_storage_devices
from tests.conftest import MockSysfsBuilder


def test_ssd_prefers_kyber_and_applies(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.add_block_device(
        "sda",
        rotational="0",
        scheduler="[mq-deadline] kyber bfq none\n",
    )
    sys_fs = DirectorySysFs(builder.sys_root)
    devices = apply_storage_schedulers(sys_fs, apply=True)

    assert len(devices) == 1
    assert devices[0].device == "sda"
    assert devices[0].rotational == 0
    assert devices[0].scheduler == "kyber"
    assert (builder.sys_root / "block" / "sda" / "queue" / "scheduler").read_text(
        encoding="utf-8"
    ) == "kyber"


def test_ssd_falls_back_to_none_and_dry_run_skips_write(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.add_block_device(
        "nvme0n1",
        rotational="0",
        scheduler="[mq-deadline] none\n",
    )
    sys_fs = DirectorySysFs(builder.sys_root)

    # Dry check (apply=False)
    detected = apply_storage_schedulers(sys_fs, apply=False)
    assert detected[0].scheduler == "none"
    assert sys_fs.writes == []
    assert (
        builder.sys_root / "block" / "nvme0n1" / "queue" / "scheduler"
    ).read_text(encoding="utf-8") == "[mq-deadline] none\n"

    # Real apply
    applied = apply_storage_schedulers(sys_fs, apply=True)
    assert applied[0].scheduler == "none"
    assert (
        builder.sys_root / "block" / "nvme0n1" / "queue" / "scheduler"
    ).read_text(encoding="utf-8") == "none"


def test_ssd_neither_kyber_nor_none_picks_safe_available() -> None:
    sys_fs = FakeSysFs(
        {
            "/sys/block/sda/queue/rotational": "0\n",
            "/sys/block/sda/queue/scheduler": "[mq-deadline] bfq\n",
        }
    )
    devices = apply_storage_schedulers(sys_fs, apply=True)
    assert len(devices) == 1
    assert devices[0].scheduler == "mq-deadline"


def test_hdd_selects_bfq_and_tunes_read_priority(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.add_block_device(
        "sdb",
        rotational="1",
        scheduler="[mq-deadline] kyber bfq none\n",
        has_iosched=True,
        read_ahead_kb="128\n",
    )
    sys_fs = DirectorySysFs(builder.sys_root)
    devices = apply_storage_schedulers(sys_fs, apply=True)

    assert len(devices) == 1
    assert devices[0].device == "sdb"
    assert devices[0].rotational == 1
    assert devices[0].scheduler == "bfq"
    assert (builder.sys_root / "block" / "sdb" / "queue" / "scheduler").read_text(
        encoding="utf-8"
    ) == "bfq"
    assert (
        builder.sys_root / "block" / "sdb" / "queue" / "iosched" / "low_latency"
    ).read_text(encoding="utf-8") == "1"
    assert (
        builder.sys_root / "block" / "sdb" / "queue" / "read_ahead_kb"
    ).read_text(encoding="utf-8") == "256"


def test_virtual_devices_skipped() -> None:
    sys_fs = FakeSysFs(
        {
            "/sys/block/loop0/queue/rotational": "0\n",
            "/sys/block/loop1/queue/rotational": "0\n",
            "/sys/block/ram0/queue/rotational": "0\n",
            "/sys/block/zram0/queue/rotational": "0\n",
            "/sys/block/sr0/queue/rotational": "1\n",
            "/sys/block/dm-0/queue/rotational": "0\n",
            "/sys/block/nbd0/queue/rotational": "0\n",
            "/sys/block/sda/queue/rotational": "0\n",
            "/sys/block/sda/queue/scheduler": "[none] kyber\n",
        }
    )
    devices = detect_storage_devices(sys_fs)
    assert [d.device for d in devices] == ["sda"]


def test_malformed_and_missing_sysfs_does_not_crash_sibling(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.add_block_device("bad_empty", rotational="", scheduler="kyber\n")
    builder.add_block_device("bad_text", rotational="invalid\n", scheduler="kyber\n")
    builder.add_block_device("no_queue", rotational=None, scheduler=None)
    builder.add_block_device("empty_sched", rotational="0\n", scheduler="   \n")
    builder.add_block_device("sda", rotational="0\n", scheduler="[mq-deadline] kyber\n")

    warnings: list[str] = []
    sys_fs = DirectorySysFs(builder.sys_root)
    devices = apply_storage_schedulers(sys_fs, apply=True, warnings=warnings)

    names = [d.device for d in devices]
    assert "sda" in names
    assert "bad_empty" not in names
    assert "bad_text" not in names
    assert "no_queue" not in names
    assert len(warnings) >= 4
    assert (builder.sys_root / "block" / "sda" / "queue" / "scheduler").read_text(
        encoding="utf-8"
    ) == "kyber"


def test_non_utf8_sysfs_entries_gracefully_skipped(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.add_block_device("sda", rotational="0\n", scheduler="[mq-deadline] kyber\n")
    builder.add_block_device("sdb", rotational="0\n", scheduler=None)
    (builder.sys_root / "block" / "sdb" / "queue" / "scheduler").write_bytes(
        b"\xff\xfe[none]\n"
    )
    builder.add_block_device("sdl", rotational=None, scheduler="kyber\n")
    (builder.sys_root / "block" / "sdl" / "queue" / "rotational").write_bytes(
        b"\xff\xfe0\n"
    )

    warnings: list[str] = []
    sys_fs = DirectorySysFs(builder.sys_root)
    devices = apply_storage_schedulers(sys_fs, apply=True, warnings=warnings)

    by_name = {d.device: d for d in devices}
    assert "sda" in by_name
    assert by_name["sda"].scheduler == "kyber"
    assert "sdb" in by_name
    assert by_name["sdb"].scheduler == "kyber"
    assert "sdl" not in by_name
    assert any("sdl" in w for w in warnings)
    assert (builder.sys_root / "block" / "sda" / "queue" / "scheduler").read_text(
        encoding="utf-8"
    ) == "kyber"
