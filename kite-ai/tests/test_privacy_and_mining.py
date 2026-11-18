"""Unit and property tests for PrivacyFilter, ContentExtractor, SimHash64, and TextRank."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kite_ai.abstractions import Clock, FileWatcher, HttpClient, SecretStore
from kite_ai.fakes import FakeClock, FakeHttpClient, InMemoryFileWatcher, InMemorySecretStore
from kite_ai.mining.extractor import extract_content, infer_platform_badge
from kite_ai.mining.simhash import cluster_near_duplicates, compute_simhash64, hamming_distance64
from kite_ai.mining.textrank import build_idf_map, extract_fingerprint_25w
from kite_ai.models import FileRecord
from kite_ai.privacy import PrivacyFilter, parse_kiteignore


def test_fakes_satisfy_kite_ai_protocols() -> None:
    assert isinstance(InMemoryFileWatcher(), FileWatcher)
    assert isinstance(InMemorySecretStore(), SecretStore)
    assert isinstance(FakeHttpClient(), HttpClient)
    assert isinstance(FakeClock(), Clock)


@pytest.mark.parametrize(
    "blocked_path",
    [
        "/home/kite/.ssh/id_rsa",
        "/home/kite/.ssh/id_ed25519",
        "/home/kite/.gnupg/secring.gpg",
        "/home/kite/project/.env",
        "/home/kite/project/.env.production",
        "/home/kite/.mozilla/firefox/default/logins.json",
        "/home/kite/.config/chromium/Default/Cookies",
        "/home/kite/.config/google-chrome/Default/Login Data",
        "/home/kite/.config/BraveSoftware/Brave-Browser/Default/Preferences",
        "/etc/shadow",
        "/etc/gshadow",
        "/home/kite/certs/server.pem",
        "/home/kite/certs/private.key",
    ],
)
def test_privacy_filter_blocks_sensitive_paths_before_disk_read(blocked_path: str) -> None:
    pf = PrivacyFilter()
    assert pf.is_blocked(blocked_path) is True


@pytest.mark.parametrize(
    "safe_path",
    [
        "/home/kite/Documents/Greenhouse_AI_Spec_v2.pdf",
        "/home/kite/Code/tent_monitor.ino",
        "/home/kite/Desktop/Agile_Report_Ch2.md",
        "/var/lib/kitebridge/apps/NotepadPP.exe",
    ],
)
def test_privacy_filter_allows_normal_user_files(safe_path: str) -> None:
    pf = PrivacyFilter()
    assert pf.is_blocked(safe_path) is False


def test_kiteignore_parser_and_custom_patterns(tmp_path: Path) -> None:
    ig = tmp_path / ".kiteignore"
    ig.write_text("# comment\nsecrets_vault/\n*.secret\n", encoding="utf-8")
    patterns = parse_kiteignore(ig.read_text(encoding="utf-8"))
    assert patterns == ["secrets_vault/", "*.secret"]

    pf = PrivacyFilter(kiteignore_path=ig)
    assert pf.is_blocked(tmp_path / "secrets_vault" / "notes.txt", root=tmp_path) is True
    assert pf.is_blocked(tmp_path / "tokens.secret", root=tmp_path) is True
    assert pf.is_blocked(tmp_path / "docs" / "notes.md", root=tmp_path) is False


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("report.pdf", "[Doc]"),
        ("notes.md", "[Doc]"),
        ("main.py", "[Code]"),
        ("tent_monitor.ino", "[Code]"),
        ("installer.exe", "[Win]"),
        ("setup.msi", "[Win]"),
        ("app.apk", "[Android]"),
        ("bundle.aab", "[Android]"),
        ("Xcode.dmg", "[macOS]"),
        ("Notes.app", "[macOS]"),
    ],
)
def test_platform_badge_inference(filename: str, expected: str) -> None:
    assert infer_platform_badge(filename) == expected


def test_extractor_markdown_python_ast_js_and_pdf(tmp_path: Path) -> None:
    md = tmp_path / "spec.md"
    md.write_text("# Greenhouse Spec\n## PID Controller\nSensor telemetry loop.\n", encoding="utf-8")
    ex_md = extract_content(md)
    assert ex_md.headings == ("Greenhouse Spec", "PID Controller")
    assert ex_md.platform_badge == "[Doc]"

    py = tmp_path / "controller.py"
    py.write_text("class PidLoop:\n    pass\ndef calibrate_sensor():\n    return 1\n", encoding="utf-8")
    ex_py = extract_content(py)
    assert "PidLoop" in ex_py.symbols and "calibrate_sensor" in ex_py.symbols
    assert ex_py.platform_badge == "[Code]"

    js = tmp_path / "ui.js"
    js.write_text("export function renderSpotlight() {}\nclass GlassCard {}\n", encoding="utf-8")
    ex_js = extract_content(js)
    assert "renderSpotlight" in ex_js.symbols and "GlassCard" in ex_js.symbols

    pdf = tmp_path / "Greenhouse.pdf"
    pdf.write_bytes(b"%PDF-1.4\n/Title (Capstone Greenhouse AI Spec)\nBT (esp32 pid sensor) Tj ET\n")
    ex_pdf = extract_content(pdf)
    assert "Capstone Greenhouse AI Spec" in ex_pdf.headings
    assert "esp32" in ex_pdf.text_sample


def test_simhash64_identical_and_near_duplicate_clustering() -> None:
    base = (
        "University capstone greenhouse automation system using esp32 temperature humidity pid control loop fan pwm "
        "soil moisture sensor relay irrigation schedule data logging calibration bill of materials chapter two "
        "microcontroller firmware architecture power budget thermal dissipation enclosure design "
    ) * 3
    draft_v2 = base + "revised conclusion"
    unrelated = "Arch Linux Hyprland Wayland compositor Dual Kawase shader blur optimization Haswell Intel HD 4400"

    h1 = compute_simhash64(base)
    h2 = compute_simhash64(draft_v2)
    h3 = compute_simhash64(unrelated)

    assert hamming_distance64(h1, h1) == 0
    assert hamming_distance64(h1, h2) <= 3
    assert hamming_distance64(h1, h3) > 3

    recs = [
        FileRecord("/docs/draft_v1.md", 1, 1000, 120, "[Doc]", h1, "capstone,greenhouse"),
        FileRecord("/docs/draft_v2.md", 2, 2000, 125, "[Doc]", h2, "capstone,greenhouse"),
        FileRecord("/docs/hyprland.md", 3, 1500, 110, "[Doc]", h3, "hyprland,haswell"),
    ]
    clusters = cluster_near_duplicates(recs, max_distance=3)
    assert clusters["/docs/draft_v1.md"] == "/docs/draft_v2.md"
    assert clusters["/docs/draft_v2.md"] == "/docs/draft_v2.md"
    assert clusters["/docs/hyprland.md"] == "/docs/hyprland.md"


def test_textrank_fingerprint_capped_at_25_words_and_boosts_headings() -> None:
    words = [f"keyword{i}" for i in range(60)]
    idf = build_idf_map([" ".join(words), "greenhouse esp32 pid"])
    fp = extract_fingerprint_25w(
        " ".join(words),
        headings=["Greenhouse Esp32"],
        symbols=["regulate_fan"],
        file_name="greenhouse_spec.md",
        idf_map=idf,
    )
    parts = [p for p in fp.split(",") if p]
    assert 1 <= len(parts) <= 25
    assert "greenhouse" in parts[:5]
    assert "esp32" in parts[:5]
