"""Tests for Contract #6 .desktop generation, PE/APK/ICNS icon extraction, and Wizard."""

from __future__ import annotations

import plistlib

from kite_bridge.config import BridgeConfig
from kite_bridge.desktop import DesktopIntegration
from kite_bridge.fakes import FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.icons import extract_icon
from kite_bridge.models import Platform, RouteDecision
from kite_bridge.wizard import InstallerWizard
from pathlib import Path as _Path
import importlib.util as _ilu
_c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
_c_mod = _ilu.module_from_spec(_c_spec)
_c_spec.loader.exec_module(_c_mod)
build_synthetic_apk = _c_mod.build_synthetic_apk
build_synthetic_icns = _c_mod.build_synthetic_icns
build_synthetic_pe_with_icon = _c_mod.build_synthetic_pe_with_icon


def test_desktop_entry_generation_and_tags() -> None:
    fs = InMemoryPrefixFilesystem()
    cfg = BridgeConfig.from_env(
        probe=FakeSystemProbe(),
        env={"HOME": "/home/kite", "XDG_DATA_HOME": "/home/kite/.local/share", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"},
    )
    desktop = DesktopIntegration(fs=fs, config=cfg)

    for plat, expected_tag, handler, src in (
        (Platform.WIN, "[Win]", "wine-ntsync", "/tmp/Foobar.exe"),
        (Platform.ANDROID, "[Android]", "waydroid-multiwindow", "/tmp/Droid.apk"),
        (Platform.MACOS, "[macOS]", "osx-kvm-bridge", "/tmp/Sketch.app"),
    ):
        decision = RouteDecision(
            path=src,
            extension=".exe",
            platform=plat,
            handler=handler,
            mime_type="application/octet-stream",
            detection_method="extension",
            dxvk_version="1.10.3" if plat == Platform.WIN else None,
            wined3d_dx12=(plat == Platform.WIN),
            command=[handler, src],
            env={"MESA_LOADER_DRIVER_OVERRIDE": "crocus", "LIBVA_DRIVER_NAME": "i965"},
        )
        spec = desktop.build_spec(decision, app_name="Sample App", icon=f"kitebridge-{plat.value}")
        written = desktop.write_desktop_entry(spec)
        text = fs.read_text(written)
        assert f"Name={expected_tag} Sample App" in text
        assert f"X-KiteBridge-Platform={plat.value}" in text

    assert len(desktop.list_entries(platform_filter="all")) == 3
    assert len(desktop.list_entries(platform_filter="macos")) == 1


def test_pure_python_icon_extractors_and_fallback() -> None:
    fs = InMemoryPrefixFilesystem()

    # 1. PE .exe icon -> .ico
    fs.write_bytes("/tmp/app.exe", build_synthetic_pe_with_icon())
    res_win = extract_icon("/tmp/app.exe", Platform.WIN, "/var/lib/kitebridge/icons", "app", fs=fs)
    assert res_win.extracted is True
    assert res_win.format == "ico"
    assert fs.read_bytes(res_win.icon_value)[:4] == b"\x00\x00\x01\x00"

    # 2. APK icon -> .png
    fs.write_bytes("/tmp/app.apk", build_synthetic_apk())
    res_apk = extract_icon("/tmp/app.apk", Platform.ANDROID, "/var/lib/kitebridge/icons", "droid", fs=fs)
    assert res_apk.extracted is True
    assert res_apk.format == "png"
    assert fs.read_bytes(res_apk.icon_value).startswith(b"\x89PNG\r\n\x1a\n")

    # 3. macOS .app .icns -> .png
    fs.write_bytes(
        "/tmp/Demo.app/Contents/Info.plist",
        plistlib.dumps({"CFBundleExecutable": "Demo", "CFBundleIconFile": "AppIcon"}),
    )
    fs.write_bytes("/tmp/Demo.app/Contents/Resources/AppIcon.icns", build_synthetic_icns())
    res_mac = extract_icon("/tmp/Demo.app", Platform.MACOS, "/var/lib/kitebridge/icons", "demo", fs=fs)
    assert res_mac.extracted is True
    assert res_mac.format == "png"
    assert fs.read_bytes(res_mac.icon_value).startswith(b"\x89PNG\r\n\x1a\n")

    # 4. Synthetic missing file -> theme fallback
    res_fb = extract_icon("/tmp/missing.exe", Platform.WIN, "/var/lib/kitebridge/icons", "missing", fs=fs)
    assert res_fb.extracted is False
    assert res_fb.icon_value == "kitebridge-win"


def test_wizard_plan_qml_vs_cli_fallback() -> None:
    cfg = BridgeConfig.from_env(probe=FakeSystemProbe(), env={"HOME": "/home/kite"})
    decision = RouteDecision(
        path="/tmp/app.exe",
        extension=".exe",
        platform=Platform.WIN,
        handler="wine-ntsync",
        mime_type="application/x-ms-dos-executable",
        detection_method="extension",
        dxvk_version="1.10.3",
        wined3d_dx12=True,
        command=["wine", "/tmp/app.exe"],
        env={"MESA_LOADER_DRIVER_OVERRIDE": "crocus", "LIBVA_DRIVER_NAME": "i965"},
    )
    runner = FakeProcessRunner(available_binaries={"qml6": "/usr/bin/qml6"})
    wiz_wayland = InstallerWizard(runner=runner, config=cfg, env={"WAYLAND_DISPLAY": "wayland-1"})
    plan_qml = wiz_wayland.build_plan(decision, app_name="App")
    assert plan_qml.mode == "qml"
    assert wiz_wayland.launch_qml(plan_qml) is True

    wiz_headless = InstallerWizard(runner=runner, config=cfg, env={})
    plan_cli = wiz_headless.build_plan(decision, app_name="App")
    assert plan_cli.mode == "cli"


def test_desktop_exec_escaping_and_wizard_plan_arg() -> None:
    fs = InMemoryPrefixFilesystem()
    cfg = BridgeConfig.from_env(
        probe=FakeSystemProbe(),
        env={"HOME": "/home/kite", "XDG_DATA_HOME": "/home/kite/.local/share", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"},
    )
    desktop = DesktopIntegration(fs=fs, config=cfg)
    decision = RouteDecision(
        path='/tmp/My "App" $v1%2.exe',
        extension=".exe",
        platform=Platform.WIN,
        handler="wine-ntsync",
        mime_type="application/x-ms-dos-executable",
        detection_method="extension",
        dxvk_version="1.10.3",
        wined3d_dx12=True,
        command=["wine", '/tmp/My "App" $v1%2.exe'],
        env={"MESA_LOADER_DRIVER_OVERRIDE": "crocus", "LIBVA_DRIVER_NAME": "i965"},
    )
    spec = desktop.build_spec(decision, app_name="My App")
    assert '\\"App\\"' in spec.exec_command
    assert "\\$v1%%2.exe" in spec.exec_command

    runner = FakeProcessRunner(available_binaries={"qml6": "/usr/bin/qml6"})
    wiz = InstallerWizard(runner=runner, config=cfg, env={"WAYLAND_DISPLAY": "wayland-1"})
    plan = wiz.build_plan(decision, app_name="My App")
    assert wiz.launch_qml(plan) is True
    assert any(arg.startswith("--plan=") for arg in runner.invocations[-1].argv)
