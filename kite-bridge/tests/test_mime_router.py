"""Tests for MIME, magic-byte, and extension routing."""

from __future__ import annotations

import plistlib
import struct

from kite_bridge.fakes import FakeHwProfileReader, FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.hw_profile import build_tier_profile
from kite_bridge.mime_router import MimeRouter
from kite_bridge.models import Platform
from pathlib import Path as _Path
import importlib.util as _ilu
_c_spec = _ilu.spec_from_file_location("_kb_conftest", _Path(__file__).with_name("conftest.py"))
_c_mod = _ilu.module_from_spec(_c_spec)
_c_spec.loader.exec_module(_c_mod)
build_synthetic_aab = _c_mod.build_synthetic_aab
build_synthetic_apk = _c_mod.build_synthetic_apk
build_synthetic_lnk = _c_mod.build_synthetic_lnk
build_synthetic_pe_with_icon = _c_mod.build_synthetic_pe_with_icon


def _make_router() -> tuple[MimeRouter, InMemoryPrefixFilesystem, FakeSystemProbe]:
    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    probe.add_char_device("/dev/ntsync")
    probe.add_char_device("/dev/binder")
    probe.add_file("/proc/pressure/memory", "some avg10=0.00")
    probe.add_file("/proc/pressure/cpu", "some avg10=0.00")
    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    router = MimeRouter(
        runner=runner,
        probe=probe,
        fs=fs,
        hw_reader=FakeHwProfileReader(build_tier_profile("8G")),
    )
    return router, fs, probe


def test_extension_fallback_routes_all_platforms() -> None:
    router, _, _ = _make_router()

    win_exe = router.inspect(r"C:\tmp\app.exe")
    assert win_exe.platform == Platform.WIN
    assert win_exe.handler == "wine-ntsync"
    assert win_exe.dxvk_version == "1.10.3"
    assert win_exe.wined3d_dx12 is True
    assert win_exe.env["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert win_exe.env["LIBVA_DRIVER_NAME"] == "i965"

    win_msi = router.inspect("/tmp/setup.msi")
    assert win_msi.command[1:3] == ["msiexec", "/i"]

    win_bat = router.inspect("/tmp/run.bat")
    assert win_bat.command[1:3] == ["cmd", "/c"]

    apk = router.inspect("/tmp/game.apk")
    assert apk.platform == Platform.ANDROID
    assert apk.handler == "waydroid-multiwindow"
    assert apk.dxvk_version is None

    aab = router.inspect("/tmp/app.aab")
    assert aab.platform == Platform.ANDROID
    assert "--mode=universal" in aab.metadata["bundletool_command"]

    dmg = router.inspect("/tmp/disk.dmg")
    assert dmg.platform == Platform.MACOS
    assert dmg.handler == "darling-dmg"

    pkg = router.inspect("/tmp/inst.pkg")
    assert pkg.platform == Platform.MACOS
    assert pkg.handler == "darling-pkg"

    macho = router.inspect("/tmp/cli_tool.macho")
    assert macho.platform == Platform.MACOS
    assert macho.handler == "darling-cli"
    assert macho.command[:2] == ["darling", "shell"]


def test_magic_byte_inspection_overrides_missing_extension() -> None:
    router, fs, _ = _make_router()

    fs.write_bytes("/tmp/noext_pe", build_synthetic_pe_with_icon())
    d_pe = router.inspect("/tmp/noext_pe")
    assert d_pe.platform == Platform.WIN
    assert d_pe.detection_method == "magic"

    fs.write_bytes("/tmp/noext_apk", build_synthetic_apk("com.kite.magic"))
    d_apk = router.inspect("/tmp/noext_apk")
    assert d_apk.platform == Platform.ANDROID
    assert d_apk.metadata["package_name"] == "com.kite.magic"

    fs.write_bytes("/tmp/noext_aab", build_synthetic_aab("com.kite.aab"))
    d_aab = router.inspect("/tmp/noext_aab")
    assert d_aab.platform == Platform.ANDROID
    assert d_aab.extension == ".aab"

    fs.write_bytes("/tmp/noext_lnk", build_synthetic_lnk(r"C:\Tools\tool.exe"))
    d_lnk = router.inspect("/tmp/noext_lnk")
    assert d_lnk.platform == Platform.WIN
    assert "tool.exe" in d_lnk.command[1]

    fs.write_bytes("/tmp/noext_dmg", b"\x00" * 512 + b"koly" + b"\x00" * 508)
    assert router.inspect("/tmp/noext_dmg").handler == "darling-dmg"

    fs.write_bytes("/tmp/noext_apfs", b"\x00" * 0x20 + b"NXSB" + b"\x00" * 64)
    assert router.inspect("/tmp/noext_apfs").handler == "apfs-fuse"

    fs.write_bytes("/tmp/noext_hfs", b"\x00" * 1024 + b"H+" + b"\x00" * 32)
    assert router.inspect("/tmp/noext_hfs").handler == "hfsprogs"

    fs.write_bytes("/tmp/macho_tool", struct.pack(">I", 0xFEEDFACF) + b"\x00" * 16)
    assert router.inspect("/tmp/macho_tool").handler == "darling-cli"


def test_app_bundle_classification_cli_vs_gui() -> None:
    router, fs, probe = _make_router()
    probe.add_char_device("/dev/kvm", rw=True)
    for asset in ("OpenCore.qcow2", "macOS.qcow2", "OVMF_CODE.fd", "OVMF_VARS.fd"):
        fs.write_bytes(f"{router.config.macos_dir}/osx-kvm/{asset}", b"asset")

    # Tier 1 CLI bundle
    cli_plist = plistlib.dumps(
        {
            "CFBundleName": "CliTool",
            "CFBundleExecutable": "clitool",
            "LSBackgroundOnly": True,
        }
    )
    fs.write_bytes("/apps/Cli.app/Contents/Info.plist", cli_plist)
    fs.write_bytes("/apps/Cli.app/Contents/MacOS/clitool", struct.pack(">I", 0xFEEDFACF))
    d_cli = router.inspect("/apps/Cli.app")
    assert d_cli.handler == "darling-cli"
    assert d_cli.command[:2] == ["darling", "shell"]

    # Tier 2 GUI bundle
    gui_plist = plistlib.dumps(
        {
            "CFBundleName": "CocoaEditor",
            "CFBundleExecutable": "CocoaEditor",
            "NSPrincipalClass": "NSApplication",
        }
    )
    fs.write_bytes("/apps/CocoaEditor.app/Contents/Info.plist", gui_plist)
    fs.write_bytes("/apps/CocoaEditor.app/Contents/MacOS/CocoaEditor", b"AppKit.framework")
    d_gui = router.inspect("/apps/CocoaEditor.app")
    assert d_gui.handler == "osx-kvm-bridge"
    assert "Haswell-noTSX,+invtsc,vendor=GenuineIntel" in d_gui.command


def test_magic_sniffing_uses_bounded_reads_without_full_read_bytes(tmp_path) -> None:
    from kite_bridge.fakes import TempPrefixFilesystem

    class NoFullReadFs(TempPrefixFilesystem):
        def read_bytes(self, path: str) -> bytes:
            raise AssertionError(f"read_bytes() must not be called for magic sniffing: {path}")

    fs = NoFullReadFs(tmp_path)
    # Create a large 16 MiB sparse .dmg image with UDIF "koly" trailer in the final 512 bytes
    dmg_file = tmp_path / "tmp" / "huge_installer.dmg"
    dmg_file.parent.mkdir(parents=True, exist_ok=True)
    with open(dmg_file, "wb") as fh:
        fh.seek(16 * 1024 * 1024 - 512)
        fh.write(b"koly" + b"\x00" * 508)

    probe = FakeSystemProbe()
    runner = FakeProcessRunner(available_binaries={"wine": "/opt/wine-cachyos/bin/wine"})
    router = MimeRouter(
        runner=runner,
        probe=probe,
        fs=fs,
        hw_reader=FakeHwProfileReader(build_tier_profile("4G")),
    )
    decision = router.inspect("/tmp/huge_installer.dmg")
    assert decision.handler == "darling-dmg"
    assert decision.detection_method == "magic+extension"
