"""Contract tests for abstractions Protocols, Fakes, and JsonHwProfileReader."""

from __future__ import annotations

import json

import pytest

from kite_bridge.abstractions import (
    CgroupController,
    HwProfileReader,
    MountManager,
    PrefixFilesystem,
    ProcessRunner,
    QmpClient,
    SystemProbe,
)
from kite_bridge.fakes import (
    FakeCgroupController,
    FakeHwProfileReader,
    FakeMountManager,
    FakeProcessRunner,
    FakeQmpClient,
    FakeSystemProbe,
    InMemoryPrefixFilesystem,
    TempDirCgroupController,
    TempPrefixFilesystem,
)
from kite_bridge.hw_profile import JsonHwProfileReader
from kite_bridge.models import DxvkVersionViolationError
from pathlib import Path as _Path
import importlib.util as _ilu
_c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
_c_mod = _ilu.module_from_spec(_c_spec)
_c_spec.loader.exec_module(_c_mod)
make_hw_profile_json = _c_mod.make_hw_profile_json


def test_fakes_satisfy_runtime_protocols(tmp_path) -> None:
    assert isinstance(FakeProcessRunner(), ProcessRunner)
    assert isinstance(FakeSystemProbe(), SystemProbe)
    assert isinstance(FakeCgroupController(), CgroupController)
    assert isinstance(TempDirCgroupController(tmp_path / "cg"), CgroupController)
    assert isinstance(InMemoryPrefixFilesystem(), PrefixFilesystem)
    assert isinstance(TempPrefixFilesystem(tmp_path / "fs"), PrefixFilesystem)
    assert isinstance(FakeMountManager(), MountManager)
    assert isinstance(FakeQmpClient(), QmpClient)
    assert isinstance(FakeHwProfileReader(), HwProfileReader)
    assert isinstance(JsonHwProfileReader(FakeSystemProbe()), HwProfileReader)


def test_fake_process_runner_records_calls() -> None:
    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    runner.set_result("wine", returncode=0, stdout="wine-9.0-cachyos")
    assert runner.which("wine") == "/opt/wine-cachyos/bin/wine"
    res = runner.run(["wine", "--version"], env={"DXVK_VER": "1.10.3"}, cwd="/tmp")
    assert res.returncode == 0
    assert "cachyos" in res.stdout
    assert len(runner.invocations) == 1
    assert runner.invocations[0].env["DXVK_VER"] == "1.10.3"


def test_temp_cgroup_and_prefix_filesystem_on_windows(tmp_path) -> None:
    cg = TempDirCgroupController(tmp_path / "cgroup")
    cg.freeze("waydroid")
    assert cg.is_frozen("waydroid") is True
    assert (tmp_path / "cgroup" / "waydroid" / "cgroup.freeze").read_text().strip() == "1"
    cg.thaw("waydroid")
    assert cg.is_frozen("waydroid") is False

    fs = TempPrefixFilesystem(tmp_path / "prefix")
    fs.mkdir("/home/kite/Documents")
    fs.symlink("/home/kite/Documents", "/var/lib/kitebridge/wine/prefixes/default/drive_c/users/kite/Documents")
    assert fs.is_symlink("/var/lib/kitebridge/wine/prefixes/default/drive_c/users/kite/Documents")
    assert fs.readlink("/var/lib/kitebridge/wine/prefixes/default/drive_c/users/kite/Documents").endswith("/home/kite/Documents")


@pytest.mark.parametrize(
    "tier,expected_policy,expected_teardown,expected_prewarm,expected_hugepages",
    [
        ("4G", "freeze_then_teardown", 300, False, False),
        ("8G", "cgroup_freeze", None, False, False),
        ("16G", "prewarmed", None, True, True),
    ],
)
def test_hw_profile_reader_parses_all_tiers(
    tier: str,
    expected_policy: str,
    expected_teardown: int | None,
    expected_prewarm: bool,
    expected_hugepages: bool,
) -> None:
    probe = FakeSystemProbe()
    probe.add_file("/run/kite-os/hw-profile.json", make_hw_profile_json(tier, "AC"))
    profile = JsonHwProfileReader(probe).read()
    assert profile.tier == tier
    assert profile.wine_dxvk_version == "1.10.3"
    assert profile.waydroid_idle_policy == expected_policy
    assert profile.waydroid_teardown_after_sec == expected_teardown
    assert profile.waydroid_prewarm is expected_prewarm
    assert profile.osx_kvm_hugepages_on_demand is expected_hugepages
    assert profile.fallback_used is False


def test_hw_profile_reader_rejects_non_1_10_3_dxvk() -> None:
    bad_ver = "2" + ".3.0"
    payload = json.loads(make_hw_profile_json("8G"))
    payload["subsystems"]["wine"]["dxvk_version"] = bad_ver
    probe = FakeSystemProbe()
    probe.add_file("/run/kite-os/hw-profile.json", json.dumps(payload))
    with pytest.raises(DxvkVersionViolationError):
        JsonHwProfileReader(probe).read()


def test_hw_profile_reader_fallback_uses_proc_meminfo_and_defaults_4g() -> None:
    probe_missing = FakeSystemProbe()
    p_default = JsonHwProfileReader(probe_missing).read()
    assert p_default.fallback_used is True
    assert p_default.tier == "4G"
    assert p_default.waydroid_teardown_after_sec == 300

    probe_16g = FakeSystemProbe()
    probe_16g.add_file("/proc/meminfo", "MemTotal:       16384000 kB\n")
    p_16g = JsonHwProfileReader(probe_16g).read()
    assert p_16g.fallback_used is True
    assert p_16g.tier == "16G"


def test_posix_system_probe_virtual_dev_overrides(monkeypatch) -> None:
    from kite_bridge.abstractions import PosixSystemProbe

    probe = PosixSystemProbe()
    monkeypatch.setenv("KITE_DEV_KVM", "1")
    monkeypatch.setenv("KITE_DEV_NTSYNC", "1")
    monkeypatch.setenv("KITE_DEV_BINDER", "1")
    assert probe.exists("/dev/kvm") and probe.is_char_device("/dev/kvm") and probe.access_rw("/dev/kvm")
    assert probe.exists("/dev/ntsync") and probe.is_char_device("/dev/ntsync")
    assert probe.glob("/dev/binder*") == ["/dev/binder"]

    monkeypatch.setenv("KITE_DEV_KVM", "0")
    assert probe.exists("/dev/kvm") is False
    assert probe.access_rw("/dev/kvm") is False


def test_inmemory_glob_recursive_and_malformed_hw_profile_fallback() -> None:
    from kite_bridge.fakes import InMemoryPrefixFilesystem

    fs = InMemoryPrefixFilesystem()
    fs.write_bytes("/mnt/dmg/Top.app/Contents/Info.plist", b"plist")
    fs.write_bytes("/mnt/dmg/Sub/Nested.app/Contents/Info.plist", b"plist")
    apps = fs.glob("/mnt/dmg", "**/*.app")
    assert "/mnt/dmg/Top.app" in apps
    assert "/mnt/dmg/Sub/Nested.app" in apps

    probe = FakeSystemProbe()
    probe.add_file("/run/kite-os/hw-profile.json", json.dumps({"ram_mb": "not-an-int", "memory": ["bad"]}))
    prof = JsonHwProfileReader(probe).read()
    assert prof.fallback_used is True
    assert prof.tier == "4G"
