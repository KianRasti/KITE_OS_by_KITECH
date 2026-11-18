"""Tests for install.sh, provision-*.sh, MIME XML, QML, and hardware invariants."""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

KITE_BRIDGE_ROOT = Path(__file__).resolve().parents[1]
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


def _bash_executable() -> str | None:
    if GIT_BASH.exists():
        return str(GIT_BASH)
    return shutil.which("bash")


@pytest.mark.parametrize(
    "rel_path",
    [
        "install.sh",
        "scripts/provision-wine.sh",
        "scripts/provision-waydroid.sh",
        "scripts/provision-macos.sh",
    ],
)
def test_shell_scripts_pass_bash_syntax_and_lf(rel_path: str) -> None:
    script = KITE_BRIDGE_ROOT / rel_path
    assert script.exists()
    raw = script.read_bytes()
    assert b"\r\n" not in raw, f"{rel_path} must use LF line endings"
    assert raw.startswith(b"#!/usr/bin/env bash\n")

    bash = _bash_executable()
    if bash is None:
        pytest.skip("bash executable unavailable")
    proc = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"bash -n failed for {rel_path}: {proc.stderr}"


def test_mime_xml_and_qml_and_script_contracts() -> None:
    xml_path = KITE_BRIDGE_ROOT / "mime" / "kitebridge-mime.xml"
    tree = ET.parse(xml_path)
    root = tree.getroot()
    globs = {el.attrib["pattern"] for el in root.findall(".//{*}glob")}
    for expected in ("*.exe", "*.msi", "*.bat", "*.lnk", "*.apk", "*.aab", "*.dmg", "*.pkg", "*.app", "*.apfs", "*.hfs"):
        assert expected in globs

    qml_text = (KITE_BRIDGE_ROOT / "mime" / "GlassInstallerWizard.qml").read_text(encoding="utf-8")
    assert "import QtQuick" in qml_text
    assert "1.10.3" in qml_text

    install_text = (KITE_BRIDGE_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "--break-system-packages" in install_text
    assert "kitebridge-mime.xml" in install_text
    assert "update-mime-database" in install_text
    assert "update-desktop-database" in install_text
    assert "/var/lib/kitebridge" in install_text

    wine_sh = (KITE_BRIDGE_ROOT / "scripts" / "provision-wine.sh").read_text(encoding="utf-8")
    assert "8d1a3c912761b450c879f98478ae64f6f6639e40ce6848170a0f6b8596fd53c6" in wine_sh
    assert "1.10.3" in wine_sh
    assert "MESA_LOADER_DRIVER_OVERRIDE=\"crocus\"" in wine_sh
    assert "LIBVA_DRIVER_NAME=\"i965\"" in wine_sh

    waydroid_sh = (KITE_BRIDGE_ROOT / "scripts" / "provision-waydroid.sh").read_text(encoding="utf-8")
    assert "persist.waydroid.multi_windows" in waydroid_sh
    assert "bundletool" in waydroid_sh

    macos_sh = (KITE_BRIDGE_ROOT / "scripts" / "provision-macos.sh").read_text(encoding="utf-8")
    for tok in ("darling-dmg", "fsck.hfsplus", "apfs-fuse", "darling", "qemu-system-x86_64", "Haswell-noTSX"):
        assert tok in macos_sh
    assert "--plan=" in qml_text
    assert "required property string modelData" in qml_text


def test_shell_script_guards_dxvk_version_and_missing_arg() -> None:
    import os

    bash = _bash_executable()
    if bash is None:
        pytest.skip("bash executable unavailable")

    wine_res = subprocess.run(
        [bash, str(KITE_BRIDGE_ROOT / "scripts" / "provision-wine.sh"), "--dry-run"],
        env={**os.environ, "DXVK_VERSION": "2" + ".3.0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert wine_res.returncode == 1
    assert "1.10.3" in wine_res.stderr

    for script_name in ("install.sh", "scripts/provision-macos.sh"):
        res = subprocess.run(
            [bash, str(KITE_BRIDGE_ROOT / script_name), "--prefix"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 2
        assert "unbound variable" not in res.stderr.lower()
