from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.tests.m1_helpers import REPO_ROOT

EXPECTED_AGENTS_SHA256 = "2c9c5fc4dc8353e4ba91c7c99c798b7db4603f6cefc882295dc5e966a3169de5"
EXPECTED_SKILL_SHA256 = "639c61b21082ebca9dcd44c95bcf075876a1ec654f94b24ed7a2168e8056ba8b"


def test_agents_md_verbatim_bytes() -> None:
    path = REPO_ROOT / "AGENTS.md"
    assert path.is_file()
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "AGENTS.md must not have UTF-8 BOM"
    assert b"\r\n" not in raw, "AGENTS.md must use LF line endings"
    assert raw.endswith(b"\n")
    assert len(raw) == 4526
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_AGENTS_SHA256
    text = raw.decode("utf-8")
    assert not text.startswith("---\n"), "AGENTS.md must not have YAML frontmatter"
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in text
    assert "DXVK must be pinned to `1.10.3`" in text


def test_skill_md_verbatim_bytes_and_em_dash() -> None:
    path = REPO_ROOT / ".agents" / "skills" / "kite-os-builder" / "SKILL.md"
    assert path.is_file()
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "SKILL.md must not have UTF-8 BOM"
    assert b"\r\n" not in raw, "SKILL.md must use LF line endings"
    assert raw.endswith(b"\n")
    assert len(raw) == 2781
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SKILL_SHA256
    text = raw.decode("utf-8")
    assert text.startswith("---\nname: kite-os-builder\n")
    assert "\u2014" in text, "UTF-8 em-dash must be preserved"
    assert "\u00e2\u20ac\u201d" not in text, "Mojibake detected"
