from __future__ import annotations

import re

from conftest import CALAMARES_DIR, INSTALLER_DIR, INSTALL_SCRIPT, VALIDATE_SCRIPT

BANNED_CALAMARES_TOKENS = (
    re.compile(r"\biris\b", re.IGNORECASE),
    re.compile(r"\biHD\b"),
    re.compile(r"\bintel-media-driver\b", re.IGNORECASE),
    re.compile(r"DXVK\s*2\.[0-9xX]", re.IGNORECASE),
)

ACTIVE_FORBIDDEN_PATTERNS = (
    re.compile(r"""MESA_LOADER_DRIVER_OVERRIDE\s*=\s*["']?iris\b"""),
    re.compile(r"""LIBVA_DRIVER_NAME\s*=\s*["']?iHD\b"""),
    re.compile(r"""DXVK(_VER)?\s*[:=]\s*["']?2\.\d+"""),
)


def test_active_crocus_and_i965_pins_present():
    shellprocess = (CALAMARES_DIR / "modules" / "shellprocess.conf").read_text(encoding="utf-8")
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in shellprocess
    assert "LIBVA_DRIVER_NAME=i965" in shellprocess

    validator = VALIDATE_SCRIPT.read_text(encoding="utf-8")
    assert "crocus" in validator
    assert "i965" in validator
    assert "anv" in validator
    assert "1.2" in validator


def test_zero_banned_tokens_in_calamares_and_install_sh():
    targets = [
        *sorted(CALAMARES_DIR.rglob("*.conf")),
        *sorted(CALAMARES_DIR.rglob("*.desc")),
        *sorted(CALAMARES_DIR.rglob("*.qss")),
        *sorted(CALAMARES_DIR.rglob("*.qml")),
        *sorted(CALAMARES_DIR.rglob("*.svg")),
        INSTALL_SCRIPT,
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for pat in BANNED_CALAMARES_TOKENS:
            assert not pat.search(text), f"Banned token {pat.pattern!r} found in {path.relative_to(INSTALLER_DIR)}"


def test_zero_active_forbidden_assignments_anywhere_in_installer():
    for path in sorted(INSTALLER_DIR.rglob("*")):
        if not path.is_file():
            continue
        if "tests" in path.relative_to(INSTALLER_DIR).parts or path.suffix == ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for pat in ACTIVE_FORBIDDEN_PATTERNS:
            assert not pat.search(text), f"Forbidden active assignment {pat.pattern!r} in {path}"


def test_validator_actively_rejects_iris_and_ihd():
    text = VALIDATE_SCRIPT.read_text(encoding="utf-8")
    assert "iris" in text
    assert "iHD" in text
    assert "intel-media-driver" in text
    assert "FAIL" in text
