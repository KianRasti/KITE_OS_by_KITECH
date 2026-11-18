"""Tests for unified CLI Contract #7 and subcommands."""

from __future__ import annotations

import json

from kite_bridge.cli import KiteBridgeApp
from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import FakeCgroupController, FakeHwProfileReader, FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.hw_profile import build_tier_profile


def _make_app(tier: str = "8G") -> tuple[KiteBridgeApp, InMemoryPrefixFilesystem]:
    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    probe.add_char_device("/dev/ntsync")
    probe.add_char_device("/dev/binder")
    probe.add_file("/proc/pressure/memory", "some avg10=0.00")
    probe.add_file("/proc/pressure/cpu", "some avg10=0.00")
    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    cfg = BridgeConfig.from_env(
        probe=probe,
        env={
            "HOME": "/home/kite",
            "XDG_DATA_HOME": "/home/kite/.local/share",
            "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge",
        },
    )
    app = KiteBridgeApp(
        runner=runner,
        probe=probe,
        fs=fs,
        cgroups=FakeCgroupController(),
        hw_reader=FakeHwProfileReader(build_tier_profile(tier)),  # type: ignore[arg-type]
        config=cfg,
    )
    return app, fs


def test_cli_inspect_and_open_dry_run_contract_7(capsys) -> None:
    app, _ = _make_app("8G")
    rc = app.run_cli(["inspect", r"C:\tmp\game.exe", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for key in ("path", "extension", "platform", "handler", "dxvk_version", "wined3d_dx12", "command", "env"):
        assert key in payload
    assert payload["platform"] == "win"
    assert payload["handler"] == "wine-ntsync"
    assert payload["dxvk_version"] == "1.10.3"
    assert payload["wined3d_dx12"] is True
    assert payload["env"]["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert payload["env"]["LIBVA_DRIVER_NAME"] == "i965"
    assert payload["env"]["DXVK_VER"] == "1.10.3"

    rc2 = app.run_cli(["open", "/tmp/setup.msi", "--dry-run", "--json"])
    assert rc2 == 0
    payload2 = json.loads(capsys.readouterr().out)
    assert payload2["command"][1:3] == ["msiexec", "/i"]


def test_cli_install_and_list_and_setup_and_status(capsys) -> None:
    app, fs = _make_app("8G")
    assert app.run_cli(["setup", "all", "--json"]) == 0
    setup_out = json.loads(capsys.readouterr().out)
    assert setup_out["dxvk_version"] == "1.10.3"
    assert fs.is_dir("/var/lib/kitebridge/wine/dxvk/1.10.3")

    assert app.run_cli(["install", "/tmp/MyApp.exe", "--name", "My App", "--no-wizard", "--json"]) == 0
    inst_out = json.loads(capsys.readouterr().out)
    assert inst_out["platform_tag"] == "[Win]"
    assert fs.exists(inst_out["desktop_entry_path"])

    assert app.run_cli(["list", "--platform", "win", "--json"]) == 0
    listed_payload = json.loads(capsys.readouterr().out)
    assert listed_payload["count"] == 1
    listed = listed_payload["applications"]
    assert len(listed) == 1
    assert listed[0]["platform"] == "win"
    assert listed[0]["platform_tag"] == "[Win]"

    assert app.run_cli(["status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["wine"]["dxvk_version"] == "1.10.3"
    assert st["haswell_env"]["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert st["haswell_env"]["LIBVA_DRIVER_NAME"] == "i965"


def test_cli_lifecycle_waydroid_4g_teardown(capsys) -> None:
    app, _ = _make_app("4G")
    assert app.run_cli(["lifecycle", "waydroid", "start", "--json"]) == 0
    capsys.readouterr()
    assert app.run_cli(["lifecycle", "waydroid", "idle-tick", "--idle-seconds", "300", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["waydroid"]["state"] == "stopped"


def test_cli_unknown_file_exits_2(capsys) -> None:
    app, _ = _make_app("8G")
    rc = app.run_cli(["inspect", "/tmp/readme.txt", "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["platform"] == "unknown"


def test_cli_default_lifecycle_and_empty_list_and_setup_details(capsys) -> None:
    app, _ = _make_app("16G")
    assert app.run_cli(["list", "--json"]) == 0
    empty_list = json.loads(capsys.readouterr().out)
    assert empty_list["count"] == 0
    assert empty_list["applications"] == []

    assert app.run_cli(["lifecycle", "--dry-run", "--json"]) == 0
    lc_out = json.loads(capsys.readouterr().out)
    assert lc_out["waydroid"]["idle_policy"] == "prewarmed"
    assert lc_out["osx_kvm"]["idle_hibernate_method"] == "savevm"

    assert app.run_cli(["setup", "--dry-run", "--json"]) == 0
    setup_out = json.loads(capsys.readouterr().out)
    assert setup_out["wine_user_folders"] == ["Desktop", "Documents", "Downloads"]
    assert setup_out["waydroid"]["persist.waydroid.multi_windows"] is True
    assert "apfs-fuse" in setup_out["macos"]["mount_tools"]


def test_cli_multi_instance_waydroid_persistence_and_hw_profile_override(capsys) -> None:
    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    probe.add_char_device("/dev/ntsync")
    probe.add_char_device("/dev/binder")
    probe.add_file("/proc/pressure/memory", "some avg10=0.00")
    probe.add_file("/proc/pressure/cpu", "some avg10=0.00")
    # Default config profile is 16G (prewarmed), while explicit --hw-profile is 4G (freeze_then_teardown)
    from pathlib import Path as _Path
    import importlib.util as _ilu
    _c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
    _c_mod = _ilu.module_from_spec(_c_spec)
    _c_spec.loader.exec_module(_c_mod)
    make_hw_profile_json = _c_mod.make_hw_profile_json

    probe.add_file("/run/kite-os/hw-profile.json", make_hw_profile_json("16G", "AC"))
    probe.add_file("/etc/hw-4g.json", make_hw_profile_json("4G", "Battery"))

    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    cgroups = FakeCgroupController()
    cfg = BridgeConfig.from_env(
        probe=probe,
        env={"HOME": "/home/kite", "XDG_DATA_HOME": "/home/kite/.local/share", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"},
    )

    # Instance 1: start Waydroid
    app1 = KiteBridgeApp(runner=runner, probe=probe, fs=fs, cgroups=cgroups, config=cfg)
    assert app1.run_cli(["lifecycle", "waydroid", "start", "--json"]) == 0
    out1 = json.loads(capsys.readouterr().out)
    assert out1["waydroid"]["state"] == "active"

    # Instance 2: separate KiteBridgeApp freezes Waydroid
    app2 = KiteBridgeApp(runner=runner, probe=probe, fs=fs, cgroups=cgroups, config=cfg)
    assert app2.run_cli(["lifecycle", "waydroid", "freeze", "--json"]) == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["waydroid"]["state"] == "frozen"
    assert cgroups.is_frozen("waydroid") is True

    # Instance 3: separate KiteBridgeApp enforces --hw-profile /etc/hw-4g.json on idle-tick 300s
    app3 = KiteBridgeApp(runner=runner, probe=probe, fs=fs, cgroups=cgroups, config=cfg)
    assert app3.run_cli(
        ["lifecycle", "waydroid", "idle-tick", "--idle-sec", "300", "--hw-profile", "/etc/hw-4g.json", "--json"]
    ) == 0
    out3 = json.loads(capsys.readouterr().out)
    assert out3["waydroid"]["tier"] == "4G"
    assert out3["waydroid"]["state"] == "stopped"
    assert ("freeze", "waydroid") in cgroups.history
    assert any(c.argv == ("waydroid", "session", "stop") for c in runner.invocations)


def test_cli_live_open_preserves_magic_extension_override_and_hw_profile(capsys) -> None:
    from pathlib import Path as _Path
    import importlib.util as _ilu
    _c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
    _c_mod = _ilu.module_from_spec(_c_spec)
    _c_spec.loader.exec_module(_c_mod)
    build_synthetic_lnk = _c_mod.build_synthetic_lnk
    make_hw_profile_json = _c_mod.make_hw_profile_json

    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    probe.add_char_device("/dev/ntsync")
    probe.add_char_device("/dev/kvm", rw=True)
    probe.add_file("/run/kite-os/hw-profile.json", make_hw_profile_json("8G", "AC"))
    probe.add_file("/etc/hw-4g.json", make_hw_profile_json("4G", "Battery"))

    runner = FakeProcessRunner(
        available_binaries={
            "wine": "/opt/wine-cachyos/bin/wine",
            "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
        }
    )
    cfg = BridgeConfig.from_env(
        probe=probe,
        env={"HOME": "/home/kite", "XDG_DATA_HOME": "/home/kite/.local/share", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"},
    )
    app = KiteBridgeApp(runner=runner, probe=probe, fs=fs, config=cfg)

    # Extensionless OLE2 .msi must execute `wine msiexec /i`, not bare `wine <path>`
    fs.write_bytes("/tmp/noext_msi", b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 64)
    assert app.run_cli(["open", "/tmp/noext_msi", "--json"]) == 0
    capsys.readouterr()
    assert runner.invocations[-1].argv == ("/opt/wine-cachyos/bin/wine", "msiexec", "/i", "/tmp/noext_msi")

    # Extensionless MS-SHLLINK .lnk must resolve target instead of bare `wine <path>`
    fs.write_bytes("/tmp/noext_lnk", build_synthetic_lnk(r"C:\Apps\editor.exe", args="--quiet"))
    assert app.run_cli(["open", "/tmp/noext_lnk", "--json"]) == 0
    capsys.readouterr()
    assert runner.invocations[-1].argv[1].endswith("/drive_c/Apps/editor.exe")
    assert "--quiet" in runner.invocations[-1].argv

    # Live open with --hw-profile 4G must enforce 4G OSX-KVM gate even when default profile is 8G
    for asset in ("OpenCore.qcow2", "macOS.qcow2", "OVMF_CODE.fd", "OVMF_VARS.fd"):
        fs.write_bytes(f"{cfg.macos_dir}/osx-kvm/{asset}", b"asset")
    fs.write_bytes("/apps/Gui.app/Contents/Info.plist", b"")
    import plistlib

    fs.write_bytes(
        "/apps/Gui.app/Contents/Info.plist",
        plistlib.dumps({"CFBundleName": "Gui", "CFBundleExecutable": "Gui", "NSPrincipalClass": "NSApplication"}),
    )
    fs.write_bytes("/apps/Gui.app/Contents/MacOS/Gui", b"AppKit.framework")
    rc = app.run_cli(["open", "/apps/Gui.app", "--hw-profile", "/etc/hw-4g.json", "--json"])
    assert rc == 1
    err = json.loads(capsys.readouterr().out)
    assert "4G" in err["error"]
