"""Tier 1 Category-Partition E2E tests for Features 9–16 (kite-hw-tune & kite-shell)."""
from __future__ import annotations

import configparser
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import (
    introspect_cli_help,
    invoke_kite_settings_cli,
    require_artifact,
    resolve_kite_settings_module,
    run_js_syntax_check,
    run_kite_hw_tune,
    run_kite_settings,
    run_qml_structural_check,
    run_sh_syntax_check,
    scan_active_forbidden_assignments,
    validate_hw_profile_v1,
    validate_settings_v1,
)

pytestmark = pytest.mark.tier1


def _assert_no_playwright_errors(page: Any) -> None:
    errs = page._kite_errors
    assert errs["console"] == [], f"Console errors: {errs['console']}"
    assert errs["page"] == [], f"Uncaught page errors: {errs['page']}"
    assert errs["http"] == [], f"HTTP >=400 responses: {errs['http']}"
    assert errs["failed"] == [], f"Failed network requests: {errs['failed']}"


def _click_any(page: Any, patterns: list[str]) -> bool:
    for pat in patterns:
        rx = re.compile(re.escape(pat), re.IGNORECASE)
        for role in ("button", "tab", "menuitem", "switch", "checkbox"):
            loc = page.get_by_role(role, name=rx)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click()
                return True
        attr_loc = page.locator(
            f"[aria-label*='{pat}' i], [title*='{pat}' i], [data-action*='{pat}' i], [data-panel*='{pat}' i]"
        )
        if attr_loc.count() > 0 and attr_loc.first.is_visible():
            attr_loc.first.click()
            return True
        txt_loc = page.get_by_text(rx)
        if txt_loc.count() > 0 and txt_loc.first.is_visible():
            txt_loc.first.click()
            return True
    return False


def _invoke_kite_settings_apply(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    *,
    preset: str | None = None,
    settings_dict: dict[str, Any] | None = None,
    hw_profile_path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Run kite_settings CLI hermetically to emit settings.json and kite-glass-runtime.conf."""
    res, loaded_settings, hypr_text = invoke_kite_settings_cli(
        repo_root,
        python_exe,
        tmp_path,
        preset=preset,
        settings_dict=settings_dict,
        hw_profile_path=hw_profile_path,
    )
    assert res.returncode == 0, f"kite_settings failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}"
    assert loaded_settings is not None, "kite_settings did not produce settings JSON"
    return loaded_settings, hypr_text


# ===========================================================================
# Feature 9: kite-hw-tune RAM Tier Engine (6 tests)
# ===========================================================================


def test_t1_f09_4g_tier_zram_and_budget(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    validate_hw_profile_v1(prof)
    assert prof["ram_mb"] == 4096
    assert prof["memory"]["tier"] == "4G"
    assert prof["memory"]["zram_percent"] == 150
    assert prof["memory"]["zram_size_mb"] == 6144
    assert prof["memory"]["zram_algo"] == "lz4"
    assert prof["memory"]["idle_budget_mb"] <= 260


def test_t1_f09_4g_tier_sysctl_blur_and_subsystems(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    sysctl = prof["memory"]["sysctl"]
    assert sysctl["vm.swappiness"] == 180
    assert sysctl["vm.page-cluster"] == 0
    assert sysctl["vm.watermark_boost_factor"] == 0
    assert prof["blur"] == {
        "tier": "static",
        "enabled": False,
        "size": 0,
        "passes": 0,
        "xray": False,
    }
    assert prof["subsystems"]["waydroid"] == {
        "idle_policy": "freeze_then_teardown",
        "teardown_after_sec": 300,
        "prewarm": False,
    }
    assert prof["subsystems"]["wine"]["prewarm"] is False
    assert prof["subsystems"]["osx_kvm"]["hugepages_on_demand"] is False


def test_t1_f09_8g_tier_zram_and_sysctl(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    validate_hw_profile_v1(prof)
    assert prof["memory"]["tier"] == "8G"
    assert prof["memory"]["zram_percent"] == 100
    assert prof["memory"]["zram_size_mb"] == 8192
    assert prof["memory"]["zram_algo"] == "zstd"
    assert 260 < prof["memory"]["idle_budget_mb"] <= 400
    sysctl = prof["memory"]["sysctl"]
    assert sysctl["vm.swappiness"] == 150
    assert sysctl["vm.page-cluster"] == 0
    assert sysctl["vm.vfs_cache_pressure"] == 75


def test_t1_f09_8g_tier_blur_and_subsystems(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    assert prof["blur"] == {
        "tier": "kawase_2pass",
        "enabled": True,
        "size": 6,
        "passes": 2,
        "xray": True,
    }
    assert prof["subsystems"]["waydroid"] == {
        "idle_policy": "cgroup_freeze",
        "teardown_after_sec": None,
        "prewarm": False,
    }
    assert prof["subsystems"]["wine"]["dxvk_version"] == "1.10.3"
    assert prof["subsystems"]["wine"]["ntsync"] is True
    assert prof["subsystems"]["osx_kvm"]["hugepages_on_demand"] is False


def test_t1_f09_16g_tier_zram_and_sysctl(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    validate_hw_profile_v1(prof)
    assert prof["memory"]["tier"] == "16G"
    assert prof["memory"]["zram_percent"] == 50
    assert prof["memory"]["zram_size_mb"] == 8192
    assert prof["memory"]["zram_algo"] == "zstd"
    sysctl = prof["memory"]["sysctl"]
    assert sysctl["vm.swappiness"] == 100
    assert sysctl["vm.page-cluster"] == 0
    assert sysctl["vm.dirty_ratio"] == 10


def test_t1_f09_16g_tier_blur_and_prewarmed_subsystems(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    assert prof["blur"] == {
        "tier": "kawase_full",
        "enabled": True,
        "size": 6,
        "passes": 2,
        "xray": True,
    }
    assert prof["subsystems"]["waydroid"] == {
        "idle_policy": "prewarmed",
        "teardown_after_sec": None,
        "prewarm": True,
    }
    assert prof["subsystems"]["wine"] == {
        "dxvk_version": "1.10.3",
        "ntsync": True,
        "prewarm": True,
    }
    assert prof["subsystems"]["osx_kvm"] == {"hugepages_on_demand": True}


# ===========================================================================
# Feature 10: kite-hw-tune Storage Scheduler (5 tests)
# ===========================================================================


def test_t1_f10_ssd_rotational_0_scheduler(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, block_devices={"sda": 0}
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    by_dev = {d["device"]: d for d in prof["storage"]}
    assert "sda" in by_dev
    assert by_dev["sda"]["rotational"] == 0
    assert by_dev["sda"]["scheduler"] in {"kyber", "none"}


def test_t1_f10_hdd_rotational_1_scheduler(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, block_devices={"sdb": 1}
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    by_dev = {d["device"]: d for d in prof["storage"]}
    assert "sdb" in by_dev
    assert by_dev["sdb"]["rotational"] == 1
    assert by_dev["sdb"]["scheduler"] == "bfq"


def test_t1_f10_mixed_ssd_and_hdd_dual_bay(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, block_devices={"sda": 0, "sdb": 1}
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    by_dev = {d["device"]: d for d in prof["storage"]}
    assert by_dev["sda"]["scheduler"] in {"kyber", "none"}
    assert by_dev["sdb"]["scheduler"] == "bfq"


def test_t1_f10_virtual_block_devices_skipped(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        block_devices={"sda": 0, "loop0": 0, "ram0": 0, "zram0": 0, "sr0": 1},
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    devs = {d["device"] for d in prof["storage"]}
    assert devs == {"sda"}


def test_t1_f10_nvme_rotational_0_handling(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, block_devices={"nvme0n1": 0}
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    by_dev = {d["device"]: d for d in prof["storage"]}
    assert by_dev["nvme0n1"]["rotational"] == 0
    assert by_dev["nvme0n1"]["scheduler"] in {"none", "kyber"}


# ===========================================================================
# Feature 11: kite-hw-tune GPU, CPU, Thermal & AC/Battery (6 tests)
# ===========================================================================


def test_t1_f11_i915_modprobe_gpu_params(repo_root: Path) -> None:
    cfg_dir = require_artifact(repo_root / "kite-hw-tune" / "config", "kite-hw-tune/config")
    combined = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in cfg_dir.rglob("*") if p.is_file())
    assert "enable_fbc=1" in combined
    assert "fastboot=1" in combined


def test_t1_f11_crocus_and_i965_env_pins(repo_root: Path) -> None:
    cfg_dir = require_artifact(repo_root / "kite-hw-tune" / "config", "kite-hw-tune/config")
    combined = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in cfg_dir.rglob("*") if p.is_file())
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in combined
    assert "LIBVA_DRIVER_NAME=i965" in combined
    assert not scan_active_forbidden_assignments(repo_root, ["kite-hw-tune"])


def test_t1_f11_intel_pstate_and_thermald_config(repo_root: Path) -> None:
    hw_dir = require_artifact(repo_root / "kite-hw-tune", "kite-hw-tune")
    cfg_dir = require_artifact(hw_dir / "config", "kite-hw-tune/config")
    all_text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in hw_dir.rglob("*")
        if p.is_file() and "tests" not in p.parts
    )
    assert "intel_pstate=active" in all_text
    assert any("thermal" in p.name.lower() for p in cfg_dir.rglob("*") if p.is_file())


def test_t1_f11_ac_power_profile_fields_8g(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="AC"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    assert prof["power"]["source"] == "AC"
    assert prof["power"]["epp"] in {"performance", "balance_performance"}
    assert prof["power"]["snd_hda_intel_power_save"] == 0
    assert prof["power"]["iwlwifi_power_save"] is False
    assert prof["blur"]["passes"] == 2
    assert prof["blur"]["tier"] == "kawase_2pass"


def test_t1_f11_battery_power_profile_fields_8g(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="Battery"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    assert prof["power"]["source"] == "Battery"
    assert prof["power"]["epp"] in {"balance_power", "power"}
    assert prof["power"]["snd_hda_intel_power_save"] == 1
    assert prof["power"]["iwlwifi_power_save"] is True
    assert prof["blur"] == {
        "tier": "kawase_1pass",
        "enabled": True,
        "size": 4,
        "passes": 1,
        "xray": True,
    }


def test_t1_f11_battery_power_profile_16g_downgrades_blur(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="Battery"
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    assert prof["power"]["source"] == "Battery"
    assert prof["power"]["snd_hda_intel_power_save"] == 1
    assert prof["power"]["iwlwifi_power_save"] is True
    assert prof["blur"] == {
        "tier": "kawase_1pass",
        "enabled": True,
        "size": 4,
        "passes": 1,
        "xray": True,
    }


# ===========================================================================
# Feature 12: kite-hw-tune Systemd & udev Integration (6 tests)
# ===========================================================================


def test_t1_f12_kite_hw_tune_service_unit_contract(repo_root: Path) -> None:
    unit = require_artifact(
        repo_root / "kite-hw-tune" / "systemd" / "kite-hw-tune.service",
        "kite-hw-tune.service",
    )
    cp = configparser.ConfigParser(strict=False)
    cp.read_string(unit.read_text(encoding="utf-8"))
    for sec in ("Unit", "Service", "Install"):
        assert sec in cp, f"Missing [{sec}] in kite-hw-tune.service"
    exec_start = cp["Service"].get("ExecStart", "")
    assert "kite-hw-tune" in exec_start or "kite_hw_tune" in exec_start
    assert "--ram-mb" not in exec_start
    assert cp["Install"].get("WantedBy", "") in {"multi-user.target", "sysinit.target"}


def test_t1_f12_kite_power_service_unit_contract(repo_root: Path) -> None:
    unit = require_artifact(
        repo_root / "kite-hw-tune" / "systemd" / "kite-power.service",
        "kite-power.service",
    )
    cp = configparser.ConfigParser(strict=False)
    cp.read_string(unit.read_text(encoding="utf-8"))
    assert "Unit" in cp and "Service" in cp
    exec_start = cp["Service"].get("ExecStart", "")
    assert "kite-hw-tune" in exec_start or "kite_hw_tune" in exec_start or "kite-power" in exec_start


def test_t1_f12_99_kite_power_rules_udev_contract(repo_root: Path) -> None:
    rule = require_artifact(
        repo_root / "kite-hw-tune" / "udev" / "99-kite-power.rules",
        "99-kite-power.rules",
    )
    text = rule.read_text(encoding="utf-8")
    assert 'SUBSYSTEM=="power_supply"' in text
    assert ("kite-power" in text or "kite-hw-tune" in text)


def test_t1_f12_99_kite_storage_rules_udev_contract(repo_root: Path) -> None:
    rule = require_artifact(
        repo_root / "kite-hw-tune" / "udev" / "99-kite-storage.rules",
        "99-kite-storage.rules",
    )
    text = rule.read_text(encoding="utf-8")
    assert 'SUBSYSTEM=="block"' in text
    assert ("rotational" in text or "kite-hw-tune" in text)
    assert ("bfq" in text and ("kyber" in text or "none" in text)) or "kite-hw-tune" in text


def test_t1_f12_hw_profile_json_schema_v1_validation(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    out_file = tmp_path / "run_kite_os" / "hw-profile.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=8192,
        power_source="AC",
        output_path=out_file,
    )
    assert res.returncode == 0, res.stderr
    assert prof is not None
    validate_hw_profile_v1(prof)


def test_t1_f12_install_sh_syntax_and_targets(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "kite-hw-tune" / "install.sh", "kite-hw-tune/install.sh")
    run_sh_syntax_check(git_bash_exe, sh)
    text = sh.read_text(encoding="utf-8")
    assert "kite-hw-tune.service" in text
    assert "99-kite-power.rules" in text
    assert "99-kite-storage.rules" in text


# ===========================================================================
# Feature 13: Hyprland Floating-First Config (kite-shell/hypr/) (6 tests)
# ===========================================================================


def test_f13_hypr_files_exist_and_valid_utf8(repo_root: Path) -> None:
    hypr_dir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    for fname in ("hyprland.conf", "keybinds.conf", "windowrules.conf", "glass.conf"):
        fpath = require_artifact(hypr_dir / fname, fname)
        raw = fpath.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"BOM found in {fname}"
        text = raw.decode("utf-8")
        assert text.strip(), f"Empty Hyprland config: {fname}"
        # Balanced braces outside # comments
        depth = 0
        for line in text.splitlines():
            clean = line.split("#", 1)[0]
            depth += clean.count("{") - clean.count("}")
            assert depth >= 0, f"Unmatched '}}' in {fname}"
        assert depth == 0, f"Unclosed '{{' in {fname}"


def test_f13_floating_first_and_layout_toggle(repo_root: Path) -> None:
    hypr_dir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    combined = "\n".join(
        require_artifact(hypr_dir / f, f).read_text(encoding="utf-8")
        for f in ("hyprland.conf", "windowrules.conf", "keybinds.conf")
    )
    assert re.search(r"float\s*(,|\s)", combined, re.IGNORECASE), "Missing floating-first window rule"
    assert "dwindle" in combined and "master" in combined


def test_f13_vfr_and_damage_tracking_enabled(repo_root: Path) -> None:
    hypr_dir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    combined = "\n".join(
        require_artifact(hypr_dir / f, f).read_text(encoding="utf-8")
        for f in ("hyprland.conf", "glass.conf")
    )
    assert re.search(r"vfr\s*=\s*true", combined, re.IGNORECASE), "misc:vfr = true missing"
    assert not re.search(r"damage_tracking\s*=\s*0", combined)


def test_f13_bounded_dual_kawase_blur_and_runtime_source(repo_root: Path) -> None:
    hypr_dir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    hypr_text = require_artifact(hypr_dir / "hyprland.conf", "hyprland.conf").read_text(
        encoding="utf-8"
    )
    glass_text = require_artifact(hypr_dir / "glass.conf", "glass.conf").read_text(
        encoding="utf-8"
    )
    combined = hypr_text + "\n" + glass_text
    assert re.search(r"size\s*=\s*6\b", combined)
    assert re.search(r"passes\s*=\s*2\b", combined)
    assert re.search(r"xray\s*=\s*true\b", combined, re.IGNORECASE)
    assert "kite-glass-runtime.conf" in hypr_text


def test_f13_win11_parity_keybinds(repo_root: Path) -> None:
    hypr_dir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    binds = "\n".join(
        require_artifact(hypr_dir / f, f).read_text(encoding="utf-8")
        for f in ("keybinds.conf", "hyprland.conf")
    )
    for pattern in (
        r"Super",
        r"bind.*\bA\b",
        r"bind.*\bN\b",
        r"bind.*\bZ\b",
        r"bind.*\bI\b",
        r"bind.*\bTab\b",
        r"bind.*ALT.*F4.*killactive",
    ):
        assert re.search(pattern, binds, re.IGNORECASE), f"Missing Win11 parity bind pattern: {pattern}"


def test_f13_haswell_graphics_invariants_in_hypr(repo_root: Path) -> None:
    require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    violations = scan_active_forbidden_assignments(repo_root, ["kite-shell/hypr"])
    assert not violations, f"Forbidden driver in Hyprland config: {violations}"


# ===========================================================================
# Feature 14: Quickshell Qt6/QML Shell (kite-shell/quickshell/) (6 tests)
# ===========================================================================


def test_f14_core_qml_modules_exist_and_parse(repo_root: Path) -> None:
    qs_dir = require_artifact(repo_root / "kite-shell" / "quickshell", "kite-shell/quickshell")
    for fname in (
        "shell.qml",
        "Taskbar.qml",
        "StartMenu.qml",
        "QuickSettings.qml",
        "NotificationCenter.qml",
        "SnapLayouts.qml",
    ):
        run_qml_structural_check(qs_dir / fname)


def test_f14_taskbar_qml_alignment_and_clusters(repo_root: Path) -> None:
    tb = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "Taskbar.qml", "Taskbar.qml"
    )
    text = tb.read_text(encoding="utf-8")
    assert "center" in text.lower() and "left" in text.lower()
    assert "start" in text.lower()
    assert "search" in text.lower()
    assert any(k in text.lower() for k in ("battery", "wifi", "volume", "clock", "date"))


def test_f14_start_menu_qml_search_badges_and_power(repo_root: Path) -> None:
    sm = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml", "StartMenu.qml"
    )
    text = sm.read_text(encoding="utf-8")
    assert "search" in text.lower()
    assert "pinned" in text.lower()
    for badge in ("[Win]", "[Android]", "[macOS]"):
        assert badge in text or badge.strip("[]").lower() in text.lower()
    for pwr in ("Sleep", "Hibernate", "Restart", "Shutdown"):
        assert pwr.lower() in text.lower()


def test_f14_quick_settings_qml_controls(repo_root: Path) -> None:
    qs = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "QuickSettings.qml", "QuickSettings.qml"
    )
    text = qs.read_text(encoding="utf-8").lower()
    for ctrl in ("wi-fi", "bluetooth", "brightness", "volume", "glass"):
        assert ctrl in text or ctrl.replace("-", "") in text


def test_f14_notification_center_qml_and_calendar(repo_root: Path) -> None:
    nc = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "NotificationCenter.qml",
        "NotificationCenter.qml",
    )
    text = nc.read_text(encoding="utf-8").lower()
    assert "notification" in text
    assert "calendar" in text


def test_f14_snap_layouts_qml_grids(repo_root: Path) -> None:
    sl = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "SnapLayouts.qml", "SnapLayouts.qml"
    )
    text = sl.read_text(encoding="utf-8").lower()
    assert "half" in text or "halves" in text or "50" in text
    assert "quarter" in text
    assert "60" in text and "40" in text


# ===========================================================================
# Feature 15: kite-settings Live Customization Studio (6 tests)
# ===========================================================================


def test_f15_settings_studio_qml_and_nav_sections(repo_root: Path) -> None:
    sdir = require_artifact(repo_root / "kite-shell" / "settings", "kite-shell/settings")
    qml_files = sorted(sdir.rglob("*.qml"))
    assert qml_files, "No QML files found in kite-shell/settings/"
    combined = ""
    for q in qml_files:
        run_qml_structural_check(q)
        combined += "\n" + q.read_text(encoding="utf-8")
    for section in (
        "System",
        "Bluetooth & devices",
        "Network & internet",
        "Personalization",
        "Apps & KiteBridge",
        "Performance & Hardware",
        "Accounts",
        "System Update",
    ):
        assert section in combined, f"Missing kite-settings nav section: {section}"


def test_f15_default_settings_json_schema_v1(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    settings, _ = _invoke_kite_settings_apply(repo_root, python_exe, tmp_path)
    validate_settings_v1(settings)
    assert settings["schema_version"] == 1
    assert settings["theme_preset"] == "Aero Blue"
    assert settings["accent_color"].upper() == "#38BDF8"
    assert settings["taskbar_alignment"] == "center"
    assert settings["transparency"] == pytest.approx(0.72)
    assert settings["blur_radius"] == 6
    assert settings["specular_edge_brightness"] == pytest.approx(0.35)
    assert settings["corner_radius"] == 12
    assert settings["animation_speed"] == pytest.approx(1.0)
    assert settings["battery_glass_autosimplify"] is True
    assert settings["mitigations_off_requested"] is False


@pytest.mark.parametrize(
    "preset_name",
    [
        "Aero Blue",
        "Frosted Obsidian",
        "Emerald Glass",
        "Sunset Mica",
        "Ultra-Light Flat",
    ],
)
def test_f15_all_five_glass_presets_supported(
    repo_root: Path, python_exe: str, tmp_path: Path, preset_name: str
) -> None:
    hw_prof = tmp_path / "hw-profile.json"
    hw_prof.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ram_mb": 8192,
                "memory": {
                    "tier": "8G",
                    "zram_percent": 100,
                    "zram_size_mb": 8192,
                    "zram_algo": "zstd",
                    "idle_budget_mb": 350,
                    "sysctl": {"vm.swappiness": 150, "vm.page-cluster": 0},
                },
                "power": {
                    "source": "AC",
                    "epp": "balance_performance",
                    "snd_hda_intel_power_save": 0,
                    "iwlwifi_power_save": False,
                },
                "blur": {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True},
                "storage": [],
                "subsystems": {
                    "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
                    "waydroid": {"idle_policy": "cgroup_freeze", "teardown_after_sec": None, "prewarm": False},
                    "osx_kvm": {"hugepages_on_demand": False},
                },
            }
        ),
        encoding="utf-8",
    )
    settings, _ = _invoke_kite_settings_apply(
        repo_root, python_exe, tmp_path, preset=preset_name, hw_profile_path=hw_prof
    )
    validate_settings_v1(settings)
    assert settings["theme_preset"] == preset_name


def test_f15_sliders_and_toggles_persist_roundtrip(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    custom = {
        "schema_version": 1,
        "theme_preset": "Emerald Glass",
        "accent_color": "#10B981",
        "taskbar_alignment": "left",
        "transparency": 0.55,
        "blur_radius": 4,
        "specular_edge_brightness": 0.5,
        "corner_radius": 8,
        "animation_speed": 1.25,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "emerald-mist",
        "battery_glass_autosimplify": True,
        "mitigations_off_requested": True,
    }
    loaded, _ = _invoke_kite_settings_apply(
        repo_root, python_exe, tmp_path, settings_dict=custom
    )
    validate_settings_v1(loaded)
    assert loaded["taskbar_alignment"] == "left"
    assert loaded["transparency"] == pytest.approx(0.55)
    assert loaded["blur_radius"] == 4
    assert loaded["corner_radius"] == 8
    assert loaded["mitigations_off_requested"] is True


def test_f15_runtime_hypr_conf_generated_on_ac(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    hw_prof = tmp_path / "hw-profile.json"
    hw_prof.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ram_mb": 8192,
                "memory": {
                    "tier": "8G",
                    "zram_percent": 100,
                    "zram_size_mb": 8192,
                    "zram_algo": "zstd",
                    "idle_budget_mb": 350,
                    "sysctl": {"vm.swappiness": 150, "vm.page-cluster": 0},
                },
                "power": {
                    "source": "AC",
                    "epp": "balance_performance",
                    "snd_hda_intel_power_save": 0,
                    "iwlwifi_power_save": False,
                },
                "blur": {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True},
                "storage": [],
                "subsystems": {
                    "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
                    "waydroid": {"idle_policy": "cgroup_freeze", "teardown_after_sec": None, "prewarm": False},
                    "osx_kvm": {"hugepages_on_demand": False},
                },
            }
        ),
        encoding="utf-8",
    )
    _, hypr_conf = _invoke_kite_settings_apply(
        repo_root, python_exe, tmp_path, hw_profile_path=hw_prof
    )
    assert hypr_conf.strip(), "kite-glass-runtime.conf was not generated"
    assert re.search(r"enabled\s*=\s*true", hypr_conf, re.IGNORECASE)
    assert re.search(r"size\s*=\s*6\b", hypr_conf)
    assert re.search(r"passes\s*=\s*2\b", hypr_conf)
    assert re.search(r"xray\s*=\s*true", hypr_conf, re.IGNORECASE)


def test_f15_kite_settings_headless_cli_json(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    require_artifact(
        repo_root / "kite-shell" / "settings" / "kite_settings",
        "kite_settings package",
    )
    module_name = resolve_kite_settings_module(repo_root, python_exe)
    help_info = introspect_cli_help(repo_root, python_exe, module_name)
    assert help_info["returncode"] == 0
    settings, hypr_conf = _invoke_kite_settings_apply(repo_root, python_exe, tmp_path)
    assert settings["schema_version"] == 1
    assert hypr_conf


# ===========================================================================
# Feature 16: Interactive Browser Preview (kite-shell/preview/) (6 tests)
# ===========================================================================


def test_f16_preview_assets_valid_js_and_offline_self_contained(
    repo_root: Path, node_exe: str
) -> None:
    pdir = require_artifact(repo_root / "kite-shell" / "preview", "kite-shell/preview")
    idx = require_artifact(pdir / "index.html", "preview index.html")
    css = require_artifact(pdir / "styles.css", "preview styles.css")
    js = require_artifact(pdir / "app.js", "preview app.js")
    assert css.read_text(encoding="utf-8").strip()
    run_js_syntax_check(node_exe, js)
    html_text = idx.read_text(encoding="utf-8")
    assert not re.search(r'<script[^>]+src=["\']https?://', html_text, re.IGNORECASE)
    assert not re.search(r'<link[^>]+href=["\']https?://', html_text, re.IGNORECASE)


def test_f16_preview_renders_zero_console_page_http_errors(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    body_text = playwright_page.locator("body").inner_text().strip()
    assert len(body_text) > 10, "Preview rendered empty body"
    _assert_no_playwright_errors(playwright_page)


def test_f16_preview_taskbar_alignment_center_left_toggle(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    taskbar = playwright_page.locator("#taskbar")
    root = playwright_page.locator("#desktop-root")
    assert taskbar.get_attribute("data-alignment") == "center"
    # Open settings if alignment toggle is inside settings studio
    _click_any(playwright_page, ["Settings", "Personalization", "kite-settings"])
    assert _click_any(playwright_page, ["Left"]), "Could not click Left alignment toggle"
    assert taskbar.get_attribute("data-alignment") == "left"
    assert root.get_attribute("data-taskbar-align") == "left"
    assert playwright_page.locator("#taskbar-align-toggle").inner_text().strip() == "LFT"
    assert _click_any(playwright_page, ["Center"]), "Could not click Center alignment toggle"
    assert taskbar.get_attribute("data-alignment") == "center"
    assert root.get_attribute("data-taskbar-align") == "center"
    _assert_no_playwright_errors(playwright_page)


def test_f16_preview_start_menu_search_platform_tags_and_power(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    assert _click_any(playwright_page, ["Start"]), "Start button not clickable"
    start_menu = playwright_page.locator("#start-menu")
    assert start_menu.is_visible(), "Start Menu did not become visible"
    assert start_menu.get_attribute("aria-hidden") == "false"

    body_text = playwright_page.locator("body").inner_text()
    for badge in ("[Win]", "[Android]", "[macOS]"):
        assert badge.lower() in body_text.lower(), f"Preview Start Menu missing badge {badge}"

    cards = playwright_page.locator("#start-apps-grid .start-app-card")
    initial_count = cards.count()
    assert initial_count >= 4

    search = playwright_page.locator("input[type='search'], input[type='text'], [role='searchbox']").first
    search.fill("Win")
    filtered_count = cards.count()
    assert 0 < filtered_count < initial_count, (
        f"Search for 'Win' did not filter Start Menu cards: {filtered_count} vs {initial_count}"
    )
    filtered_texts = [cards.nth(i).inner_text() for i in range(filtered_count)]
    assert all("[Win]" in txt or "win" in txt.lower() for txt in filtered_texts), (
        f"Unexpected non-Win card after filtering 'Win': {filtered_texts}"
    )
    search.fill("")
    assert cards.count() == initial_count

    assert _click_any(playwright_page, ["Power"]), "Power button not clickable"
    power_menu = playwright_page.locator("#power-menu")
    assert power_menu.is_visible(), "Power menu did not open"
    power_txt = power_menu.inner_text().lower()
    assert all(p in power_txt for p in ("sleep", "restart", "shutdown"))
    _assert_no_playwright_errors(playwright_page)


def test_f16_preview_quick_settings_notifications_and_snap_layouts(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    assert _click_any(playwright_page, ["Quick Settings", "Win+A", "Wi-Fi", "Volume"]), (
        "Quick Settings trigger not found"
    )
    assert playwright_page.locator("#quick-settings").is_visible(), "Quick Settings flyout not visible"
    assert playwright_page.locator("#quick-settings").get_attribute("aria-hidden") == "false"

    assert _click_any(playwright_page, ["Notification", "Win+N", "Calendar"]), (
        "Notifications trigger not found"
    )
    assert playwright_page.locator("#notification-center").is_visible(), "Notification Center not visible"
    assert not playwright_page.locator("#quick-settings").is_visible()

    assert _click_any(playwright_page, ["Snap", "Win+Z", "Layout"]), (
        "Snap Layouts trigger not found"
    )
    assert playwright_page.locator("#snap-layouts").is_visible(), "Snap Layouts flyout not visible"
    assert not playwright_page.locator("#notification-center").is_visible()
    playwright_page.locator('[data-snap="left-half"]').click()
    assert playwright_page.locator("#win-kite-settings").get_attribute("data-snap-zone") == "left-half"
    _assert_no_playwright_errors(playwright_page)


def test_f16_preview_live_glass_settings_and_hw_switcher(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    assert _click_any(playwright_page, ["Settings", "Personalization", "Studio"])
    root = playwright_page.locator("#desktop-root")
    conf_preview = playwright_page.locator('[data-testid="runtime-conf-preview"]')
    json_preview = playwright_page.locator('[data-testid="settings-json-preview"]')

    for preset in ("Frosted Obsidian", "Ultra-Light Flat", "Aero Blue"):
        assert _click_any(playwright_page, [preset]), f"Preset '{preset}' not clickable"
        assert preset in json_preview.inner_text(), f"settings.json preview missing preset {preset}"

    expected_states = [
        ("4G", "4G", "AC", "static"),
        ("8G", "8G", "AC", "kawase_2pass"),
        ("16G", "16G", "AC", "kawase_full"),
        ("Battery", "16G", "Battery", "kawase_1pass"),
        ("AC", "16G", "AC", "kawase_full"),
    ]
    for hw, exp_tier, exp_power, exp_blur in expected_states:
        assert _click_any(playwright_page, [hw]), f"Hardware control '{hw}' not clickable"
        assert root.get_attribute("data-hw-tier") == exp_tier
        assert root.get_attribute("data-power") == exp_power
        assert root.get_attribute("data-blur-mode") == exp_blur
    assert "passes = 2" in conf_preview.inner_text()
    _assert_no_playwright_errors(playwright_page)
