"""Tests for Android subsystem: Waydroid multi-window, APK/AAB, and 4G/8G/16G lifecycle."""

from __future__ import annotations

import io
import zipfile

from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import (
    FakeCgroupController,
    FakeHwProfileReader,
    FakeProcessRunner,
    FakeSystemProbe,
    InMemoryPrefixFilesystem,
    TempDirCgroupController,
)
from kite_bridge.hw_profile import build_tier_profile
from kite_bridge.models import WaydroidState
from kite_bridge.waydroid import WaydroidLifecycleManager, WaydroidSubsystem, inspect_android_archive
from pathlib import Path as _Path
import importlib.util as _ilu
_c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
_c_mod = _ilu.module_from_spec(_c_spec)
_c_spec.loader.exec_module(_c_mod)
build_synthetic_aab = _c_mod.build_synthetic_aab
build_synthetic_apk = _c_mod.build_synthetic_apk


def test_apk_and_aab_inspection_and_bundletool_pipeline() -> None:
    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    probe.add_char_device("/dev/binder")
    probe.add_file("/proc/pressure/memory", "some avg10=0.00")
    probe.add_file("/proc/pressure/cpu", "some avg10=0.00")
    runner = FakeProcessRunner(available_binaries={"waydroid": "/usr/bin/waydroid", "bundletool": "/usr/bin/bundletool"})
    cfg = BridgeConfig.from_env(probe=probe, env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})

    fs.write_bytes("/tmp/sample.apk", build_synthetic_apk("com.example.kiteapp"))
    fs.write_bytes("/tmp/sample.aab", build_synthetic_aab("com.example.kitebundle"))

    apk_info = inspect_android_archive("/tmp/sample.apk", fs=fs, runner=runner)
    assert apk_info.package_name == "com.example.kiteapp"
    assert "arm64-v8a" in apk_info.abis

    wd = WaydroidSubsystem(
        runner=runner,
        probe=probe,
        fs=fs,
        cgroups=FakeCgroupController(),
        hw_reader=FakeHwProfileReader(build_tier_profile("8G")),
        config=cfg,
    )
    wd.configure_properties(arm_translation="libndk")
    prop_text = fs.read_text(cfg.waydroid_prop_path)
    assert "persist.waydroid.multi_windows=true" in prop_text
    assert "libndk_translation.so" in prop_text

    # Stage fake bundletool output universal.apk
    plan_aab = wd.plan_launch("/tmp/sample.aab")
    cache_dir = plan_aab.metadata["universal_apk"].rsplit("/", 1)[0]
    apks_buf = io.BytesIO()
    with zipfile.ZipFile(apks_buf, "w") as zf:
        zf.writestr("universal.apk", build_synthetic_apk("com.example.kitebundle"))
    fs.write_bytes(f"{cache_dir}/bundle.apks", apks_buf.getvalue())

    dec, _ = wd.install_and_launch("/tmp/sample.aab", dry_run=False)
    assert dec.extension == ".aab"
    assert fs.exists(dec.metadata["universal_apk"])
    cmds = [c.argv for c in runner.invocations]
    assert any("--mode=universal" in argv for argv in cmds)
    assert any(argv[:3] == ("waydroid", "app", "install") for argv in cmds)
    assert any(argv == ("waydroid", "app", "launch", "com.example.kitebundle") for argv in cmds)


def test_waydroid_lifecycle_4g_freeze_and_300s_teardown(tmp_path) -> None:
    now_box = [0.0]
    runner = FakeProcessRunner()
    cg = TempDirCgroupController(tmp_path / "cgroups")
    mgr = WaydroidLifecycleManager(
        runner=runner,
        probe=FakeSystemProbe(),
        cgroups=cg,
        hw_reader=FakeHwProfileReader(build_tier_profile("4G")),
        clock=lambda: now_box[0],
    )

    assert mgr.prewarm() == WaydroidState.STOPPED
    assert mgr.ensure_active() == WaydroidState.ACTIVE

    # Idle at t=0 -> immediate cgroup.freeze=1
    assert mgr.on_idle(now=0.0) == WaydroidState.FROZEN
    assert cg.is_frozen("waydroid") is True

    # t=299 -> still FROZEN
    assert mgr.tick(now=299.0) == WaydroidState.FROZEN

    # Re-activate before 300s cancels teardown
    assert mgr.ensure_active() == WaydroidState.ACTIVE
    assert cg.is_frozen("waydroid") is False
    assert mgr.idle_since is None

    # Idle again at t=1000 -> tick at 1300 tears down
    mgr.on_idle(now=1000.0)
    assert mgr.tick(now=1299.0) == WaydroidState.FROZEN
    assert mgr.tick(now=1300.0) == WaydroidState.STOPPED
    assert any(c.argv == ("waydroid", "session", "stop") for c in runner.invocations)


def test_waydroid_lifecycle_8g_and_16g() -> None:
    cg8 = FakeCgroupController()
    mgr8 = WaydroidLifecycleManager(
        runner=FakeProcessRunner(),
        probe=FakeSystemProbe(),
        cgroups=cg8,
        hw_reader=FakeHwProfileReader(build_tier_profile("8G")),
    )
    mgr8.ensure_active()
    mgr8.on_idle(now=0.0)
    assert mgr8.tick(now=3600.0) == WaydroidState.FROZEN
    assert cg8.is_frozen("waydroid") is True

    cg16 = FakeCgroupController()
    mgr16 = WaydroidLifecycleManager(
        runner=FakeProcessRunner(),
        probe=FakeSystemProbe(),
        cgroups=cg16,
        hw_reader=FakeHwProfileReader(build_tier_profile("16G")),
    )
    assert mgr16.prewarm() == WaydroidState.ACTIVE
    assert mgr16.on_idle(now=0.0) == WaydroidState.ACTIVE
    assert mgr16.tick(now=3600.0) == WaydroidState.ACTIVE
    assert cg16.is_frozen("waydroid") is False


def test_inspect_android_archive_handles_dummy_non_zip_gracefully() -> None:
    fs = InMemoryPrefixFilesystem()
    fs.write_bytes("/tmp/dummy.apk", b"KITE_DUMMY_SAMPLE")
    fs.write_bytes("/tmp/dummy.aab", b"PK")
    apk = inspect_android_archive("/tmp/dummy.apk", fs=fs)
    aab = inspect_android_archive("/tmp/dummy.aab", fs=fs)
    assert apk.kind == "apk" and apk.has_manifest is False and apk.package_name is None
    assert aab.kind == "aab" and aab.has_manifest is False and aab.package_name is None
