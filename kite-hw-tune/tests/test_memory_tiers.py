"""Tests for /proc/meminfo parsing, RAM tier classification, zram, sysctl, and subsystems."""

from __future__ import annotations

import pytest

from kite_hw_tune.abstractions import DirectoryProcFs, FakeEnvWriter, FakeProcFs
from kite_hw_tune.models import HardwareDetectionError
from kite_hw_tune.ram import (
    apply_memory_tuning,
    build_memory_profile,
    build_subsystems_profile,
    classify_ram_tier,
    detect_ram_mb,
    parse_meminfo_kb,
)
from tests.conftest import RecordingRunner


def test_parse_meminfo_standard_and_tabs() -> None:
    proc = FakeProcFs(
        {
            "/proc/meminfo": (
                "MemTotal:        8052340 kB\n"
                "MemFree:         2000000 kB\n"
            )
        }
    )
    assert parse_meminfo_kb(proc) == 8052340
    assert detect_ram_mb(proc) == 7863

    proc_tab = FakeProcFs({"/proc/meminfo": "MemTotal:\t16777216\tkB   \n"})
    assert parse_meminfo_kb(proc_tab) == 16777216
    assert detect_ram_mb(proc_tab) == 16384


@pytest.mark.parametrize(
    "content",
    [
        "",
        "MemFree: 1024 kB\n",
        "MemTotal: not_a_number kB\n",
        "MemTotal: 0 kB\n",
        "MemTotal: -4096 kB\n",
    ],
)
def test_parse_meminfo_invalid_raises(content: str) -> None:
    proc = FakeProcFs({"/proc/meminfo": content})
    with pytest.raises((HardwareDetectionError, ValueError)):
        parse_meminfo_kb(proc)


def test_parse_meminfo_missing_file_raises() -> None:
    proc = FakeProcFs({})
    with pytest.raises(HardwareDetectionError):
        parse_meminfo_kb(proc)


def test_non_utf8_proc_meminfo_raises_hardware_detection_error(tmp_path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "meminfo").write_bytes(b"\xff\xfeMemTotal: 8052340 kB\n")
    proc = DirectoryProcFs(proc_root)
    with pytest.raises(HardwareDetectionError):
        detect_ram_mb(proc)


@pytest.mark.parametrize(
    ("ram_mb", "expected_tier"),
    [
        (1024, "4G"),
        (3840, "4G"),
        (4096, "4G"),
        (6143, "4G"),
        (6144, "8G"),
        (7863, "8G"),
        (8192, "8G"),
        (12288, "8G"),
        (12289, "16G"),
        (16000, "16G"),
        (16384, "16G"),
        (32768, "16G"),
    ],
)
def test_ram_tier_boundaries(ram_mb: int, expected_tier: str) -> None:
    assert classify_ram_tier(ram_mb) == expected_tier


def test_memory_profile_exact_keys_and_zram() -> None:
    m4 = build_memory_profile(4096)
    assert m4.tier == "4G"
    assert m4.zram_percent == 150
    assert m4.zram_size_mb == 6144
    assert m4.zram_algo == "lz4"
    assert m4.idle_budget_mb == 260
    assert m4.sysctl == {
        "vm.swappiness": 180,
        "vm.page-cluster": 0,
        "vm.watermark_boost_factor": 0,
    }
    assert set(m4.sysctl.keys()) == {
        "vm.swappiness",
        "vm.page-cluster",
        "vm.watermark_boost_factor",
    }

    m8 = build_memory_profile(8192)
    assert m8.tier == "8G"
    assert m8.zram_percent == 100
    assert m8.zram_size_mb == 8192
    assert m8.zram_algo == "zstd"
    assert m8.idle_budget_mb == 350
    assert m8.sysctl == {
        "vm.swappiness": 150,
        "vm.page-cluster": 0,
        "vm.vfs_cache_pressure": 75,
    }
    assert set(m8.sysctl.keys()) == {
        "vm.swappiness",
        "vm.page-cluster",
        "vm.vfs_cache_pressure",
    }

    m16 = build_memory_profile(16384)
    assert m16.tier == "16G"
    assert m16.zram_percent == 50
    assert m16.zram_size_mb == 8192
    assert m16.zram_algo == "zstd"
    assert m16.idle_budget_mb == 480
    assert m16.sysctl == {
        "vm.swappiness": 100,
        "vm.page-cluster": 0,
        "vm.dirty_ratio": 10,
    }
    assert set(m16.sysctl.keys()) == {
        "vm.swappiness",
        "vm.page-cluster",
        "vm.dirty_ratio",
    }


def test_subsystems_by_tier() -> None:
    s4 = build_subsystems_profile("4G")
    assert s4.wine.dxvk_version == "1.10.3"
    assert s4.wine.ntsync is True
    assert s4.wine.prewarm is False
    assert s4.waydroid.idle_policy == "freeze_then_teardown"
    assert s4.waydroid.teardown_after_sec == 300
    assert s4.waydroid.prewarm is False
    assert s4.osx_kvm.hugepages_on_demand is False

    s8 = build_subsystems_profile("8G")
    assert s8.wine.dxvk_version == "1.10.3"
    assert s8.wine.ntsync is True
    assert s8.wine.prewarm is False
    assert s8.waydroid.idle_policy == "cgroup_freeze"
    assert s8.waydroid.teardown_after_sec is None
    assert s8.waydroid.prewarm is False
    assert s8.osx_kvm.hugepages_on_demand is False

    s16 = build_subsystems_profile("16G")
    assert s16.wine.dxvk_version == "1.10.3"
    assert s16.wine.ntsync is True
    assert s16.wine.prewarm is True
    assert s16.waydroid.idle_policy == "prewarmed"
    assert s16.waydroid.teardown_after_sec is None
    assert s16.waydroid.prewarm is True
    assert s16.osx_kvm.hugepages_on_demand is True


def test_apply_memory_tuning_commands_and_dry_run() -> None:
    mem4 = build_memory_profile(4096)
    runner = RecordingRunner()
    writer = FakeEnvWriter()

    warnings = apply_memory_tuning(mem4, runner, writer, dry_run=False)
    assert warnings == []
    assert ("sysctl", "-w", "vm.swappiness=180") in runner.history
    assert ("sysctl", "-w", "vm.page-cluster=0") in runner.history
    assert ("sysctl", "-w", "vm.watermark_boost_factor=0") in runner.history
    assert (
        "zramctl",
        "/dev/zram0",
        "--size",
        "6144M",
        "--algorithm",
        "lz4",
    ) in runner.history
    assert ("mkswap", "/dev/zram0") in runner.history
    assert ("swapon", "-p", "100", "/dev/zram0") in runner.history
    assert "/run/sysctl.d/99-kite-hw-tune.conf" in writer.written

    dry_runner = RecordingRunner()
    dry_writer = FakeEnvWriter()
    apply_memory_tuning(mem4, dry_runner, dry_writer, dry_run=True)
    assert dry_runner.history == []
    assert dry_writer.written == {}
