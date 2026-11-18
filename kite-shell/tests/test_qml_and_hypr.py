"""Structural QML validator, Hyprland config invariants, Bash syntax, and preview asset hygiene tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FORBIDDEN_TOKENS = ("iris", "intel-media-driver", "iHD", "DXVK 2.")


def _find_bash() -> str | None:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.exists():
        return str(git_bash)
    if os.name != "nt":
        return shutil.which("bash")
    return None


def _check_balanced_delimiters(text: str, file_path: Path) -> None:
    """Comment- and string-aware delimiter balance check for QML/JS/Hyprland configs."""
    stack: list[str] = []
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = {v: k for k, v in pairs.items()}

    i = 0
    n = len(text)
    in_line_comment = False
    in_block_comment = False
    in_string: str | None = None

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_string is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "#" and file_path.suffix == ".conf":
            in_line_comment = True
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = ch
            i += 1
            continue

        if ch in pairs:
            stack.append(ch)
        elif ch in closing:
            assert stack and stack[-1] == closing[ch], (
                f"Unbalanced '{ch}' in {file_path} at offset {i}; stack={stack}"
            )
            stack.pop()
        i += 1

    assert not in_block_comment, f"Unclosed block comment in {file_path}"
    assert in_string is None, f"Unclosed string literal in {file_path}"
    assert not stack, f"Unclosed delimiters {stack} in {file_path}"


def test_qml_structural_and_qt6_compliance(kite_shell_dir: Path) -> None:
    quickshell_dir = kite_shell_dir / "quickshell"
    settings_dir = kite_shell_dir / "settings"

    required_qml = [
        quickshell_dir / "shell.qml",
        quickshell_dir / "ShellState.qml",
        quickshell_dir / "Taskbar.qml",
        quickshell_dir / "StartMenu.qml",
        quickshell_dir / "QuickSettings.qml",
        quickshell_dir / "NotificationCenter.qml",
        quickshell_dir / "SnapLayouts.qml",
        quickshell_dir / "components" / "GlassPanel.qml",
        quickshell_dir / "components" / "PlatformBadge.qml",
        quickshell_dir / "components" / "AppIcon.qml",
        settings_dir / "SettingsApp.qml",
    ]
    for path in required_qml:
        assert path.exists(), f"Missing required QML file: {path}"

    qml_files = list(quickshell_dir.rglob("*.qml")) + list(settings_dir.rglob("*.qml"))
    assert len(qml_files) >= 18

    for qml_file in qml_files:
        raw = qml_file.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM forbidden in {qml_file}"
        text = raw.decode("utf-8")
        _check_balanced_delimiters(text, qml_file)
        assert "import QtGraphicalEffects" not in text, f"Qt5 QtGraphicalEffects forbidden in {qml_file}"
        assert not re.search(r"^\s*import\s+QtQuick\s+2\.", text, re.MULTILINE), (
            f"Use unversioned Qt6 imports in {qml_file}"
        )
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"Forbidden token {token!r} found in {qml_file}"

        # Every delegate block must declare required property for Qt6 ComponentBehavior
        if "delegate:" in text:
            assert "required property" in text, f"Missing 'required property' on delegate in {qml_file}"

    # Verify key functional contracts across shell QML
    shell_state_text = (quickshell_dir / "ShellState.qml").read_text(encoding="utf-8")
    assert "settings.json" in shell_state_text
    assert "/run/kite-os/hw-profile.json" in shell_state_text

    start_text = (quickshell_dir / "StartMenu.qml").read_text(encoding="utf-8")
    for tag in ("[Win]", "[Android]", "[macOS]", "Sleep", "Hibernate", "Restart", "Shutdown"):
        assert tag in start_text, f"StartMenu.qml missing {tag}"

    qs_text = (quickshell_dir / "QuickSettings.qml").read_text(encoding="utf-8")
    assert "Pipewire" in qs_text
    assert "PwObjectTracker" in qs_text
    assert "isStream && isSink" not in qs_text
    assert "!n.isSink" in qs_text or "!modelData.isSink" in qs_text

    assert 'id.indexOf("win") !== -1' not in shell_state_text
    assert "kitebridge-win" in shell_state_text

    notif_text = (quickshell_dir / "NotificationCenter.qml").read_text(encoding="utf-8")
    assert "id: notifCard" in notif_text
    assert "notifCard.platform" in notif_text
    assert "parent.parent.parent" not in notif_text

    pers_text = (settings_dir / "pages" / "PersonalizationPage.qml").read_text(encoding="utf-8")
    assert "currentIndex: page.springCurveIndex" in pers_text

    slider_text = (settings_dir / "components" / "GlassSlider.qml").read_text(encoding="utf-8")
    assert "Connections" in slider_text
    assert "Component.onCompleted" in slider_text

    preview_pane_text = (settings_dir / "components" / "LivePreviewPane.qml").read_text(encoding="utf-8")
    assert "specular_edge_brightness !== undefined" in preview_pane_text

    app_qml_text = (settings_dir / "SettingsApp.qml").read_text(encoding="utf-8")
    sidebar_qml_text = (settings_dir / "components" / "SidebarNav.qml").read_text(encoding="utf-8")
    assert "searchFilter: root.searchFilter" in app_qml_text
    assert "filteredCategories" in sidebar_qml_text

    snap_text = (quickshell_dir / "SnapLayouts.qml").read_text(encoding="utf-8")
    assert "left-half" in snap_text and "split-60" in snap_text and "top-left" in snap_text


def test_hyprland_configs_and_invariants(kite_shell_dir: Path) -> None:
    hypr_dir = kite_shell_dir / "hypr"
    for name in ("hyprland.conf", "glass.conf", "windowrules.conf", "keybinds.conf"):
        conf_path = hypr_dir / name
        assert conf_path.exists(), f"Missing {conf_path}"
        text = conf_path.read_text(encoding="utf-8")
        _check_balanced_delimiters(text, conf_path)
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"Forbidden token {token!r} found in {conf_path}"

    hyprland_conf = (hypr_dir / "hyprland.conf").read_text(encoding="utf-8")
    assert "env = MESA_LOADER_DRIVER_OVERRIDE,crocus" in hyprland_conf
    assert "env = LIBVA_DRIVER_NAME,i965" in hyprland_conf
    assert re.search(r"misc\s*\{[^}]*vfr\s*=\s*true", hyprland_conf, re.DOTALL)
    glass_pos = hyprland_conf.index("glass.conf")
    runtime_pos = hyprland_conf.index("kite-glass-runtime.conf")
    assert runtime_pos > glass_pos, "kite-glass-runtime.conf must be sourced AFTER glass.conf"

    glass_conf = (hypr_dir / "glass.conf").read_text(encoding="utf-8")
    assert "size = 6" in glass_conf
    assert "passes = 2" in glass_conf
    assert "xray = true" in glass_conf

    winrules_conf = (hypr_dir / "windowrules.conf").read_text(encoding="utf-8")
    assert "windowrulev2 = float, class:.*" in winrules_conf

    keybinds_conf = (hypr_dir / "keybinds.conf").read_text(encoding="utf-8")
    for expected in ("toggleStartMenu", "toggleQuickSettings", "toggleNotifications", "toggleSnapLayouts", "dwindle", "master"):
        assert expected in keybinds_conf


def test_no_forbidden_tokens_in_settings_or_preview_or_install(kite_shell_dir: Path) -> None:
    for subdir in ("settings", "preview"):
        for path in (kite_shell_dir / subdir).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".qml", ".html", ".css", ".js", ""}:
                text = path.read_text(encoding="utf-8")
                for token in FORBIDDEN_TOKENS:
                    assert token not in text, f"Forbidden token {token!r} found in {path}"


def test_preview_offline_and_node_syntax(kite_shell_dir: Path) -> None:
    preview_dir = kite_shell_dir / "preview"
    index_html = (preview_dir / "index.html").read_text(encoding="utf-8")
    styles_css = (preview_dir / "styles.css").read_text(encoding="utf-8")
    app_js = (preview_dir / "app.js").read_text(encoding="utf-8")

    assert "data:image/svg+xml" in index_html
    for content in (index_html, styles_css, app_js):
        scrubbed = content.replace("http://www.w3.org/2000/svg", "")
        assert "http://" not in scrubbed and "https://" not in scrubbed, "Preview must be 100% offline"

    node_bin = shutil.which("node")
    if node_bin:
        res = subprocess.run([node_bin, "--check", str(preview_dir / "app.js")], capture_output=True, text=True)
        assert res.returncode == 0, f"node --check failed: {res.stderr}"


def test_bash_scripts_syntax_and_install_dry_run(kite_shell_dir: Path, tmp_path: Path) -> None:
    bash_bin = _find_bash()
    if bash_bin is None:
        pytest.skip("Git Bash / POSIX bash not found")

    for script in (kite_shell_dir / "install.sh", kite_shell_dir / "settings" / "kite-settings"):
        res = subprocess.run([bash_bin, "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, f"bash -n failed for {script}: {res.stderr}"

    stage_root = tmp_path / "stage"
    dry = subprocess.run(
        [
            bash_bin,
            str(kite_shell_dir / "install.sh"),
            "--dry-run",
            "--prefix", "/usr/local",
            "--destdir", str(stage_root),
            "--skel",
        ],
        capture_output=True,
        text=True,
    )
    assert dry.returncode == 0, f"install.sh --dry-run failed: {dry.stderr}"
    assert "[dry-run]" in dry.stdout
    assert not stage_root.exists(), "--dry-run must not mutate filesystem"


def test_install_sh_custom_prefix_and_destdir_skel_staging(
    kite_shell_dir: Path, tmp_path: Path
) -> None:
    bash_bin = _find_bash()
    if bash_bin is None:
        pytest.skip("Git Bash / POSIX bash not found")

    install_sh = kite_shell_dir / "install.sh"

    # Missing argument guard for --prefix / --destdir / --config-dir
    missing_arg = subprocess.run(
        [bash_bin, str(install_sh), "--prefix"],
        capture_output=True,
        text=True,
    )
    assert missing_arg.returncode == 2

    # Custom --prefix /opt/kite staging and launcher execution
    opt_stage = tmp_path / "opt_stage"
    res = subprocess.run(
        [
            bash_bin,
            str(install_sh),
            "--destdir", str(opt_stage),
            "--prefix", "/opt/kite",
            "--config-dir", "/home/kite/.config",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"install.sh failed: {res.stderr}"

    launcher = opt_stage / "opt" / "kite" / "bin" / "kite-settings"
    assert launcher.exists()

    env = {**os.environ, "KITE_PYTHON": sys.executable}
    cli_res = subprocess.run(
        [bash_bin, str(launcher), "--cli", "presets", "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert cli_res.returncode == 0, f"custom prefix launcher failed: {cli_res.stderr}"
    payload = json.loads(cli_res.stdout)
    assert len(payload["presets"]) == 5

    # --destdir + --skel without explicit --config-dir skips user CONFIG_DIR staging
    skel_stage = tmp_path / "skel_stage"
    skel_res = subprocess.run(
        [
            bash_bin,
            str(install_sh),
            "--destdir", str(skel_stage),
            "--prefix", "/opt/kite",
            "--skel",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": "/home/buildhost_sentinel", "XDG_CONFIG_HOME": "/home/buildhost_sentinel/.config"},
    )
    assert skel_res.returncode == 0, f"skel staging failed: {skel_res.stderr}"
    assert (skel_stage / "etc" / "skel" / ".config" / "kite-os" / "settings.json").exists()
    assert (skel_stage / "opt" / "kite" / "bin" / "kite-settings").exists()
    assert not (skel_stage / "home" / "buildhost_sentinel").exists()


@pytest.mark.parametrize(
    "qml_rel,expected_tokens",
    [
        ("quickshell/Taskbar.qml", ("Win+S", "Behavior on implicitWidth")),
        ("quickshell/StartMenu.qml", ("kite-ai", "aiSpotlightCards")),
        ("settings/pages/PerformanceHardwarePage.qml", ("GridLayout", "columns: 2", "kite-aid.socket")),
        ("settings/pages/AiIndexingPage.qml", ("SecretStore", "150", "800", ".kiteignore")),
        ("settings/components/SidebarNav.qml", ("ai-indexing", "AI & Indexing")),
        ("settings/SettingsApp.qml", ("AiIndexingPage",)),
        ("hypr/keybinds.conf", ("$mainMod, S", "kite:toggleStartMenu")),
    ],
)
def test_phase6_shell_v2_qml_and_hypr_contracts(
    kite_shell_dir: Path, qml_rel: str, expected_tokens: tuple[str, ...]
) -> None:
    path = kite_shell_dir / qml_rel
    assert path.exists(), f"Missing {path}"
    text = path.read_text(encoding="utf-8")
    for tok in expected_tokens:
        assert tok in text, f"{qml_rel} missing Phase 6 token {tok!r}"


@pytest.mark.parametrize(
    "rel_path,expected_tokens",
    [
        ("preview/index.html", ("ai-spotlight", "bento-grid", "pane-ai-indexing", "tb-pill-dot")),
        ("preview/styles.css", ("border-top:", "border-left:", ".bento-grid", "#ai-spotlight")),
        ("preview/app.js", ("SPOTLIGHT_CORPUS", "renderSpotlightResults", "kite://open?path=")),
    ],
)
def test_phase6_preview_v2_static_contracts(
    kite_shell_dir: Path, rel_path: str, expected_tokens: tuple[str, ...]
) -> None:
    text = (kite_shell_dir / rel_path).read_text(encoding="utf-8")
    for tok in expected_tokens:
        assert tok in text, f"{rel_path} missing {tok!r}"
