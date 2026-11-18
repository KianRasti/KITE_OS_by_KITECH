from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from conftest import BRANDING_DIR


def _strip_c_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _strip_qml_comments(text: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", no_block)


def _assert_balanced_delimiters(text: str, label: str) -> None:
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = {v: k for k, v in pairs.items()}
    stack: list[str] = []
    in_quote: str | None = None
    escaped = False

    for ch in text:
        if escaped:
            escaped = False
            continue
        if in_quote is not None:
            if ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
        elif ch in pairs:
            stack.append(ch)
        elif ch in closing:
            assert stack and stack[-1] == closing[ch], f"{label}: unbalanced '{ch}'"
            stack.pop()

    assert in_quote is None, f"{label}: unclosed string literal {in_quote}"
    assert not stack, f"{label}: unclosed delimiters {stack}"


def test_qss_structural_integrity():
    qss_path = BRANDING_DIR / "stylesheet.qss"
    raw_bytes = qss_path.read_bytes()
    assert b"\r\n" not in raw_bytes, "stylesheet.qss must use LF line endings"
    text = raw_bytes.decode("utf-8")
    assert text.strip()

    stripped = _strip_c_comments(text)
    _assert_balanced_delimiters(stripped, "stylesheet.qss")
    assert "#38BDF8" in text
    assert "rgba(" in text
    assert "border-radius: 12px" in text


def test_qss_referenced_assets_exist():
    text = (BRANDING_DIR / "stylesheet.qss").read_text(encoding="utf-8")
    for match in re.finditer(r"url\(([^)]+)\)", text):
        ref = match.group(1).strip().strip("\"'")
        if ref.startswith(("http://", "https://", "data:")):
            continue
        assert (BRANDING_DIR / ref).is_file(), f"Missing QSS referenced asset: {ref}"


def test_qml_structural_integrity():
    qml_files = sorted(BRANDING_DIR.glob("*.qml"))
    assert qml_files, "Expected at least show.qml in branding/kite-os/"

    for qml_path in qml_files:
        raw_bytes = qml_path.read_bytes()
        assert b"\r\n" not in raw_bytes, f"{qml_path.name} must use LF line endings"
        text = raw_bytes.decode("utf-8")
        _assert_balanced_delimiters(_strip_qml_comments(text), qml_path.name)

    show_text = (BRANDING_DIR / "show.qml").read_text(encoding="utf-8")
    assert "import QtQuick\n" in show_text
    assert "import calamares.slideshow 1.0" in show_text
    assert "Presentation {" in show_text
    assert "function onActivate()" in show_text
    assert "function onLeave()" in show_text
    assert "radius: 12" in show_text
    assert "radius: 11" in show_text

    for match in re.finditer(r'"(assets/[^"]+)"', show_text):
        asset = BRANDING_DIR / match.group(1)
        assert asset.is_file() and asset.stat().st_size > 0, f"Missing QML asset: {match.group(1)}"


def test_svg_assets_well_formed():
    expected_svgs = {
        "kite-icon.svg",
        "kite-logo.svg",
        "kite-welcome.svg",
        "slide-haswell.svg",
        "slide-hwtune.svg",
        "slide-glass.svg",
        "slide-bridge.svg",
    }
    assets_dir = BRANDING_DIR / "assets"
    found = {p.name for p in assets_dir.glob("*.svg")}
    assert expected_svgs.issubset(found), f"Missing SVGs: {expected_svgs - found}"

    for svg_path in sorted(assets_dir.glob("*.svg")):
        raw = svg_path.read_bytes()
        assert b"\r\n" not in raw, f"{svg_path.name} must use LF line endings"
        root = ET.fromstring(raw.decode("utf-8"))
        assert root.tag.endswith("svg"), f"{svg_path.name} root tag is {root.tag}"
