"""Tests for Windows subsystem: Wine-CachyOS/Proton-GE, /dev/ntsync, 4-layer DXVK 1.10.3, and .lnk."""

from __future__ import annotations

import json

import pytest

from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import FakeHwProfileReader, FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.hw_profile import build_tier_profile
from kite_bridge.models import DxvkVersionViolationError, HwProfile, Vkd3dForbiddenError
from kite_bridge.wine import WineRuntimeSelector, WineSubsystem, parse_lnk
from pathlib import Path as _Path
import importlib.util as _ilu
_c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
_c_mod = _ilu.module_from_spec(_c_spec)
_c_spec.loader.exec_module(_c_mod)
build_synthetic_lnk = _c_mod.build_synthetic_lnk


def _wine_setup():
    probe = FakeSystemProbe()
    probe.add_char_device("/dev/ntsync")
    fs = InMemoryPrefixFilesystem()
    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    runner.set_result("wine", stdout="wine-9.0-cachyos")
    cfg = BridgeConfig.from_env(
        probe=probe,
        env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"},
    )
    wine = WineSubsystem(
        runner=runner,
        probe=probe,
        fs=fs,
        hw_reader=FakeHwProfileReader(build_tier_profile("8G")),
        config=cfg,
    )
    return wine, runner, probe, fs, cfg


def test_wine_runtime_selector_cachyos_and_proton_ge() -> None:
    probe = FakeSystemProbe()
    probe.add_file("/opt/wine-cachyos/bin/wine", b"bin")
    runner = FakeProcessRunner()
    cfg = BridgeConfig.from_env(probe=probe, env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})
    sel = WineRuntimeSelector(runner=runner, probe=probe, config=cfg)
    rt = sel.select_runtime()
    assert rt.binary == "/opt/wine-cachyos/bin/wine"
    assert rt.flavor == "wine-cachyos"

    # Fallback to highest GE-Proton version
    probe2 = FakeSystemProbe()
    probe2.add_file("/var/lib/kitebridge/wine/runners/GE-Proton8-32/files/bin/wine", b"bin")
    probe2.add_file("/var/lib/kitebridge/wine/runners/GE-Proton9-20/files/bin/wine", b"bin")
    sel2 = WineRuntimeSelector(runner=FakeProcessRunner(), probe=probe2, config=cfg)
    rt2 = sel2.select_runtime()
    assert "GE-Proton9-20" in rt2.binary
    assert rt2.flavor == "proton-ge"


def test_dxvk_1_10_3_4_layer_enforcement_and_wined3d_dx12() -> None:
    wine, _, _, fs, cfg = _wine_setup()

    env, warnings = wine.build_env(debug_ntsync=True)
    assert warnings == []
    assert env["DXVK_VER"] == "1.10.3"
    assert env["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert env["LIBVA_DRIVER_NAME"] == "i965"
    assert env["WINE_NTSYNC"] == "1"
    assert env["WINEESYNC"] == "0"
    assert env["WINEFSYNC"] == "0"
    assert env["WINEDEBUG"] == "+ntsync"
    assert env["WINE_D3D_CONFIG"] == "renderer=gl"
    assert "d3d9=n,b" in env["WINEDLLOVERRIDES"]
    assert "d3d10core=n,b" in env["WINEDLLOVERRIDES"]
    assert "d3d11=n,b" in env["WINEDLLOVERRIDES"]
    assert "dxgi=n,b" in env["WINEDLLOVERRIDES"]
    assert "d3d12=b;d3d12core=b" in env["WINEDLLOVERRIDES"]

    # Layer 1: Reject non-1.10.3 versions programmatically
    for bad in ("2" + ".0.0", "2" + ".3.1", "v2" + ".4", "1.9.2"):
        with pytest.raises(DxvkVersionViolationError):
            wine.build_env(base_env={"DXVK_VER": bad})

    with pytest.raises(Vkd3dForbiddenError):
        wine.build_env(base_env={"PROTON_USE_VKD3D": "1"})

    # Layer 2: Reject bad hw-profile dxvk_version
    bad_profile = HwProfile(wine_dxvk_version="2" + ".1.0")
    with pytest.raises(DxvkVersionViolationError):
        wine.build_env(profile=bad_profile)

    # Layer 3: Reject bad prefix manifest
    prefix = cfg.wine_prefix
    fs.write_text(
        f"{prefix}/.kitebridge-manifest.json",
        json.dumps({"dxvk_version": "2" + ".0", "wined3d_dx12": True}),
    )
    with pytest.raises(DxvkVersionViolationError):
        wine.verify_prefix(prefix)

    # Layer 4: Reject forbidden vkd3d DLL and native d3d12 in user.reg
    fs.write_text(
        f"{prefix}/.kitebridge-manifest.json",
        json.dumps({"dxvk_version": "1.10.3", "wined3d_dx12": True}),
    )
    fs.write_bytes(f"{prefix}/drive_c/windows/system32/vkd3d_test.dll", b"bad")
    with pytest.raises(Vkd3dForbiddenError):
        wine.verify_prefix(prefix)

    fs.remove(f"{prefix}/drive_c/windows/system32/vkd3d_test.dll")
    fs.write_text(f"{prefix}/user.reg", '[Software\\\\Wine\\\\DllOverrides]\n"d3d12"="native,builtin"\n')
    with pytest.raises(Vkd3dForbiddenError):
        wine.verify_prefix(prefix)


def test_wine_ensure_prefix_and_user_folder_mapping() -> None:
    wine, runner, _, fs, cfg = _wine_setup()
    # Populate fake DXVK 1.10.3 DLLs
    for arch in ("x64", "x32"):
        for dll in ("d3d9.dll", "d3d10core.dll", "d3d11.dll", "dxgi.dll"):
            fs.write_bytes(f"{cfg.wine_dxvk_dir}/{arch}/{dll}", f"{arch}-{dll}".encode())

    manifest = wine.ensure_prefix()
    assert manifest["dxvk_version"] == "1.10.3"
    assert manifest["wined3d_dx12"] is True
    assert manifest["mapped_folders"] == ["Desktop", "Documents", "Downloads"]
    assert fs.is_symlink(f"{cfg.wine_prefix}/drive_c/users/kite/Documents")
    assert fs.readlink(f"{cfg.wine_prefix}/drive_c/users/kite/Documents") == "/home/kite/Documents"
    assert len(manifest["dll_sha256"]) == 8
    assert wine.verify_prefix() == []
    assert any("wineboot" in call.argv for call in runner.invocations)


def test_wine_lnk_parser_and_routing() -> None:
    wine, _, _, fs, cfg = _wine_setup()
    raw_lnk = build_synthetic_lnk(r"C:\Program Files\Demo\demo.exe", args="--safe", workdir=r"C:\Program Files\Demo")
    parsed = parse_lnk(raw_lnk, prefix_path=cfg.wine_prefix)
    assert parsed is not None
    assert parsed.target_posix_path == f"{cfg.wine_prefix}/drive_c/Program Files/Demo/demo.exe"
    assert parsed.arguments == "--safe"

    fs.write_bytes("/tmp/demo.lnk", raw_lnk)
    dec = wine.plan_launch("/tmp/demo.lnk")
    assert dec.command[1] == f"{cfg.wine_prefix}/drive_c/Program Files/Demo/demo.exe"
    assert "--safe" in dec.command

    # Non-existent .lnk falls back to wine start /unix
    dec_fb = wine.plan_launch("/tmp/missing.lnk")
    assert dec_fb.command[1:3] == ["start", "/unix"]


def test_subprocess_runner_and_build_env_prevent_vkd3d_parent_leak(monkeypatch) -> None:
    import sys
    from kite_bridge.abstractions import SubprocessRunner

    wine, _, _, _, _ = _wine_setup()
    monkeypatch.setenv("PROTON_USE_VKD3D", "1")
    with pytest.raises(Vkd3dForbiddenError):
        wine.build_env()

    monkeypatch.setenv("VKD3D_CONFIG", "dxr")
    res = SubprocessRunner().run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('PROTON_USE_VKD3D', 'NONE'), os.environ.get('VKD3D_CONFIG', 'NONE'))",
        ]
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "NONE NONE"


def test_map_user_folders_bak_collision_and_env_user(monkeypatch) -> None:
    probe = FakeSystemProbe()
    fs = InMemoryPrefixFilesystem()
    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    monkeypatch.setenv("USER", "alice")
    monkeypatch.setenv("HOME", "/home/alice")
    cfg = BridgeConfig.from_env(probe=probe)
    wine = WineSubsystem(
        runner=runner,
        probe=probe,
        fs=fs,
        hw_reader=FakeHwProfileReader(build_tier_profile("8G")),
        config=cfg,
    )

    user_docs = f"{cfg.wine_prefix}/drive_c/users/alice/Documents"
    fs.write_text(f"{user_docs}/old.txt", "keep1")
    fs.write_text(f"{user_docs}.bak/older.txt", "keep0")
    wine.map_user_folders()
    assert fs.is_symlink(user_docs)
    assert fs.exists(f"{user_docs}.bak/older.txt")
    assert fs.exists(f"{user_docs}.bak.1/old.txt")


def test_dxvk_and_vkd3d_anti_bypass_hardening(monkeypatch) -> None:
    import json
    import sys
    from kite_bridge.abstractions import SubprocessRunner
    from kite_bridge.models import DxvkVersionViolationError

    wine, _, _, fs, _ = _wine_setup()

    # 1. WINEDLLOVERRIDES .dll suffix & * prefix bypass blocked
    env, _ = wine.build_env(base_env={"WINEDLLOVERRIDES": "d3d11.dll=b;*d3d12=n;*d3d12core.dll=n;winemenubuilder.exe="})
    assert "d3d11.dll" not in env["WINEDLLOVERRIDES"]
    assert "*d3d12" not in env["WINEDLLOVERRIDES"]
    assert "winemenubuilder.exe=" in env["WINEDLLOVERRIDES"]

    # 2. Manifest missing or empty dxvk_version fails closed
    fs.write_text(f"{wine.config.wine_prefix}/.kitebridge-manifest.json", json.dumps({"wined3d_dx12": True}))
    with pytest.raises(DxvkVersionViolationError):
        wine.verify_prefix()
    fs.write_text(f"{wine.config.wine_prefix}/.kitebridge-manifest.json", json.dumps({"dxvk_version": "", "wined3d_dx12": True}))
    with pytest.raises(DxvkVersionViolationError):
        wine.verify_prefix()
    fs.remove(f"{wine.config.wine_prefix}/.kitebridge-manifest.json")

    # 3. DXVK_VERSION=2.0 parent os.environ leak blocked in build_env(base_env={}) and SubprocessRunner
    monkeypatch.setenv("DXVK_VERSION", "2.0")
    with pytest.raises(DxvkVersionViolationError):
        wine.build_env(base_env={})
    res = SubprocessRunner().run(
        [sys.executable, "-c", "import os; print(os.environ.get('DXVK_VERSION', 'NONE'))"]
    )
    assert res.returncode == 0
    assert res.stdout.strip() == "NONE"

    # 4. libvkd3d*.dll prefix DLL and user.reg AppDefaults / *d3d12.dll native overrides blocked
    fs.write_bytes(f"{wine.config.wine_prefix}/drive_c/windows/system32/libvkd3d-1.dll", b"MZ")
    with pytest.raises(Vkd3dForbiddenError):
        wine.verify_prefix()
    fs.remove(f"{wine.config.wine_prefix}/drive_c/windows/system32/libvkd3d-1.dll")

    fs.write_text(
        f"{wine.config.wine_prefix}/user.reg",
        '[Software\\\\Wine\\\\AppDefaults\\\\game.exe\\\\DllOverrides]\n"*d3d12.dll"="native,builtin"\n',
    )
    with pytest.raises(Vkd3dForbiddenError):
        wine.verify_prefix()
