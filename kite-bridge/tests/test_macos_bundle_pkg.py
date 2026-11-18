"""Tests for macOS .app bundle Info.plist (XML & binary) and .pkg extraction."""

from __future__ import annotations

import plistlib

import pytest

from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.macos.bundle import AppBundleParser
from kite_bridge.macos.packages import PkgHandler
from kite_bridge.models import InvalidAppBundleError


def test_app_bundle_xml_and_binary_plist_and_tier_classification() -> None:
    fs = InMemoryPrefixFilesystem()
    parser = AppBundleParser(fs=fs)

    # Binary bplist00 GUI bundle
    plist_bin = plistlib.dumps(
        {
            "CFBundleDisplayName": "Notes Studio",
            "CFBundleIdentifier": "com.example.NotesStudio",
            "CFBundleExecutable": "NotesStudio",
            "CFBundleIconFile": "AppIcon",
            "CFBundleShortVersionString": "2.1",
            "NSPrincipalClass": "NSApplication",
        },
        fmt=plistlib.FMT_BINARY,
    )
    fs.write_bytes("/apps/Notes.app/Contents/Info.plist", plist_bin)
    fs.write_bytes("/apps/Notes.app/Contents/MacOS/NotesStudio", b"\xcf\xfa\xed\xfeAppKit.framework")
    fs.write_bytes("/apps/Notes.app/Contents/Resources/AppIcon.icns", b"icns\x00\x00\x00\x08")

    info = parser.parse("/apps/Notes.app")
    assert info.is_binary_plist is True
    assert info.bundle_name == "Notes Studio"
    assert info.icon_path == "/apps/Notes.app/Contents/Resources/AppIcon.icns"
    assert info.tier == "osx_kvm"
    assert info.is_gui is True

    # XML plist CLI background tool -> Darling Tier 1
    plist_xml = plistlib.dumps(
        {
            "CFBundleName": "MachHelper",
            "CFBundleExecutable": "machhelper",
            "LSBackgroundOnly": True,
        },
        fmt=plistlib.FMT_XML,
    )
    fs.write_bytes("/apps/Helper.app/Contents/Info.plist", plist_xml)
    fs.write_bytes("/apps/Helper.app/Contents/MacOS/machhelper", b"\xcf\xfa\xed\xfe")
    cli_info = parser.parse("/apps/Helper.app")
    assert cli_info.is_binary_plist is False
    assert cli_info.tier == "darling"
    assert cli_info.is_gui is False

    # Missing CFBundleExecutable raises InvalidAppBundleError
    fs.write_bytes("/apps/Broken.app/Contents/Info.plist", plistlib.dumps({"CFBundleName": "Broken"}))
    with pytest.raises(InvalidAppBundleError):
        parser.parse("/apps/Broken.app")


def test_pkg_inspect_and_extract() -> None:
    fs = InMemoryPrefixFilesystem()
    runner = FakeProcessRunner(available_binaries={"xar": "/usr/bin/xar", "bsdtar": "/usr/bin/bsdtar"})
    runner.set_result("xar", stdout="Distribution\nApp.pkg/Payload\nApp.app\n")
    cfg = BridgeConfig.from_env(probe=FakeSystemProbe(), env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})
    pkg = PkgHandler(runner=runner, fs=fs, config=cfg)

    staging = pkg._staging_dir("/tmp/Installer.pkg")
    fs.write_text(
        f"{staging}/Distribution",
        '<?xml version="1.0"?><installer-gui-script><title>Demo App</title>'
        '<pkg-ref id="com.example.demo" version="1.4.0"/></installer-gui-script>',
    )
    fs.write_bytes(f"{staging}/App.pkg/Payload", b"\x1f\x8bpayload")

    insp = pkg.inspect_pkg("/tmp/Installer.pkg")
    assert insp.package_format == "product-archive"
    assert insp.identifier == "com.example.demo"
    assert insp.version == "1.4.0"
    assert insp.title == "Demo App"

    ext = pkg.extract_pkg("/tmp/Installer.pkg", "/tmp/pkg-out")
    assert ext.extracted_to == "/tmp/pkg-out"
    assert any(c.argv[0] == "/usr/bin/bsdtar" for c in runner.invocations)


def test_pkg_inspect_extracts_distribution_via_xar_xf() -> None:
    from kite_bridge.models import CommandResult

    fs = InMemoryPrefixFilesystem()
    runner = FakeProcessRunner(available_binaries={"xar": "/usr/bin/xar"})
    cfg = BridgeConfig.from_env(probe=FakeSystemProbe(), env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})
    pkg = PkgHandler(runner=runner, fs=fs, config=cfg)

    def _xar_handler(argv, _env, _cwd):
        if argv[1] == "-tf":
            return CommandResult(argv=tuple(argv), returncode=0, stdout="Distribution\nPayload\n")
        if argv[1] == "-xf":
            c_idx = argv.index("-C")
            target_dir = argv[c_idx + 1]
            if "Distribution" in argv:
                fs.write_text(
                    f"{target_dir}/Distribution",
                    '<?xml version="1.0"?><installer-gui-script><title>Fresh Pkg</title>'
                    '<pkg-ref id="com.example.fresh" version="2.0.1"/></installer-gui-script>',
                )
        return CommandResult(argv=tuple(argv), returncode=0)

    runner.add_handler(lambda argv: argv[0] == "/usr/bin/xar", _xar_handler)
    insp = pkg.inspect_pkg("/tmp/Fresh.pkg")
    assert insp.identifier == "com.example.fresh"
    assert insp.version == "2.0.1"
    assert insp.title == "Fresh Pkg"
    assert any("-xf" in c.argv and "Distribution" in c.argv for c in runner.invocations)


def test_app_bundle_string_zero_lsuielement_runs_gui_osx_kvm() -> None:
    import plistlib
    from kite_bridge.macos.bundle import AppBundleParser

    fs = InMemoryPrefixFilesystem()
    plist_bytes = plistlib.dumps({
        "CFBundleIdentifier": "com.example.strbool",
        "CFBundleExecutable": "StrBool",
        "LSUIElement": "0",
        "LSBackgroundOnly": "false",
    })
    fs.write_bytes("/mnt/App.app/Contents/Info.plist", plist_bytes)
    fs.write_bytes("/mnt/App.app/Contents/MacOS/StrBool", b"\xfe\xed\xfa\xcf")
    info = AppBundleParser(fs=fs).parse("/mnt/App.app")
    assert info.tier == "osx_kvm"
    assert info.is_gui is True
