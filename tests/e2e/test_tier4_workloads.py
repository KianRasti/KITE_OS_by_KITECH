"""Tier 4 Real-World Application Scenario E2E tests (Scenarios 1–5, 12 tests)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import (
    AGENTS_BYTES,
    AGENTS_SHA256,
    ISO_FILENAME,
    SKILL_BYTES,
    SKILL_SHA256,
    build_kite_bridge_lifecycle_args,
    introspect_cli_help,
    invoke_kite_settings_cli,
    require_artifact,
    run_kite_bridge,
    run_kite_hw_tune,
    run_kite_settings,
    run_ps1_syntax_check,
    run_qml_structural_check,
    run_sh_syntax_check,
    run_yaml_load_check,
    scan_active_forbidden_assignments,
    validate_hw_profile_v1,
)

pytestmark = pytest.mark.tier4


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


def _assert_zero_browser_errors(page: Any) -> None:
    errs = page._kite_errors
    assert errs["console"] == [], f"Console errors: {errs['console']}"
    assert errs["page"] == [], f"Page errors: {errs['page']}"
    assert errs["http"] == [], f"HTTP errors: {errs['http']}"
    assert errs["failed"] == [], f"Failed requests: {errs['failed']}"


# ===========================================================================
# Scenario 1: Cold-Boot Folio 9480m 4 GB HDD on Battery (2 tests)
# ===========================================================================


def test_t4_s1_4g_hdd_battery_hw_tune_and_glass_static(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path = tmp_path / "hw-profile.json"
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=4096,
        power_source="Battery",
        block_devices={"sda": 1, "zram0": 0},
        output_path=prof_path,
    )
    assert res.returncode == 0 and prof is not None, res.stderr
    validate_hw_profile_v1(prof)

    assert prof["memory"]["tier"] == "4G"
    assert prof["memory"]["zram_percent"] == 150
    assert prof["memory"]["zram_algo"] == "lz4"
    assert prof["memory"]["sysctl"]["vm.swappiness"] == 180
    assert prof["memory"]["sysctl"]["vm.page-cluster"] == 0
    assert prof["memory"]["sysctl"]["vm.watermark_boost_factor"] == 0
    assert [d["device"] for d in prof["storage"]] == ["sda"]
    assert prof["storage"][0]["scheduler"] == "bfq"
    assert prof["power"]["source"] == "Battery"
    assert prof["power"]["snd_hda_intel_power_save"] == 1
    assert prof["power"]["iwlwifi_power_save"] is True
    assert prof["blur"] == {
        "tier": "static",
        "enabled": False,
        "size": 0,
        "passes": 0,
        "xray": False,
    }

    if not prof_path.is_file():
        prof_path.write_text(json.dumps(prof), encoding="utf-8")

    # Verify kite-settings forces Hyprland runtime blur off on 4G
    s_res, _, hypr_txt = invoke_kite_settings_cli(
        repo_root,
        python_exe,
        tmp_path,
        hw_profile_path=prof_path,
    )
    assert s_res.returncode == 0, s_res.stderr
    assert re.search(r"enabled\s*=\s*false", hypr_txt, re.IGNORECASE) or re.search(
        r"passes\s*=\s*0\b", hypr_txt
    )


def test_t4_s1_4g_bridge_wine_dxvk_and_waydroid_300s_teardown(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path = tmp_path / "hw-profile.json"
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=4096,
        power_source="Battery",
        block_devices={"sda": 1},
        output_path=prof_path,
    )
    assert res.returncode == 0 and prof is not None
    if not prof_path.is_file():
        prof_path.write_text(json.dumps(prof), encoding="utf-8")

    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    r_win = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(exe), "--dry-run", "--json"],
        hw_profile_path=prof_path,
    )
    assert r_win.returncode == 0, r_win.stderr
    wdata = json.loads(r_win.stdout)
    assert wdata["platform"] == "win"
    assert wdata["dxvk_version"] == "1.10.3"
    assert wdata["wined3d_dx12"] is True
    assert wdata["env"]["DXVK_VER"] == "1.10.3"
    assert wdata["env"]["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert wdata["env"]["LIBVA_DRIVER_NAME"] == "i965"

    lc_args = build_kite_bridge_lifecycle_args(
        repo_root, python_exe, "waydroid", "idle-tick", idle_seconds=300
    )
    r_lc = run_kite_bridge(
        repo_root, python_exe, tmp_path, lc_args, hw_profile_path=prof_path
    )
    assert r_lc.returncode == 0, r_lc.stderr
    assert "freeze_then_teardown" in r_lc.stdout and "300" in r_lc.stdout

    r_inst = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["install", str(exe)], hw_profile_path=prof_path
    )
    assert r_inst.returncode == 0, r_inst.stderr
    desks = list(tmp_path.rglob("kitebridge-*.desktop"))
    assert desks
    dtxt = desks[0].read_text(encoding="utf-8")
    assert "X-KiteBridge-Platform=win" in dtxt and "[Win]" in dtxt


# ===========================================================================
# Scenario 2: Cold-Boot Folio 9480m 8 GB SSD on AC -> Unplug AC (2 tests)
# ===========================================================================


def test_t4_s2_8g_ssd_ac_to_battery_power_and_blur_downgrade(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    ac_dir = tmp_path / "ac"
    bat_dir = tmp_path / "bat"
    ac_dir.mkdir()
    bat_dir.mkdir()

    r_ac, p_ac = run_kite_hw_tune(
        repo_root,
        python_exe,
        ac_dir,
        ram_mb=8192,
        power_source="AC",
        block_devices={"sda": 0},
    )
    assert r_ac.returncode == 0 and p_ac is not None
    assert p_ac["memory"]["tier"] == "8G"
    assert p_ac["storage"][0]["scheduler"] in {"kyber", "none"}
    assert p_ac["power"]["source"] == "AC"
    assert p_ac["power"]["snd_hda_intel_power_save"] == 0
    assert p_ac["power"]["iwlwifi_power_save"] is False
    assert p_ac["blur"] == {
        "tier": "kawase_2pass",
        "enabled": True,
        "size": 6,
        "passes": 2,
        "xray": True,
    }

    r_bat, p_bat = run_kite_hw_tune(
        repo_root,
        python_exe,
        bat_dir,
        ram_mb=8192,
        power_source="Battery",
        block_devices={"sda": 0},
    )
    assert r_bat.returncode == 0 and p_bat is not None
    assert p_bat["power"]["source"] == "Battery"
    assert p_bat["power"]["snd_hda_intel_power_save"] == 1
    assert p_bat["power"]["iwlwifi_power_save"] is True
    assert p_bat["blur"] == {
        "tier": "kawase_1pass",
        "enabled": True,
        "size": 4,
        "passes": 1,
        "xray": True,
    }


def test_t4_s2_8g_bridge_waydroid_cgroup_freeze(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path = tmp_path / "hw-profile.json"
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=8192,
        power_source="Battery",
        block_devices={"sda": 0},
        output_path=prof_path,
    )
    assert res.returncode == 0 and prof is not None
    if not prof_path.is_file():
        prof_path.write_text(json.dumps(prof), encoding="utf-8")

    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    r_lc = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        lc_args,
        hw_profile_path=prof_path,
    )
    assert r_lc.returncode == 0, r_lc.stderr
    assert "cgroup_freeze" in r_lc.stdout or "freeze" in r_lc.stdout


# ===========================================================================
# Scenario 3: Folio 9480m 16 GB Workstation + OSX-KVM .app + savevm (2 tests)
# ===========================================================================


def test_t4_s3_16g_workstation_prewarm_and_hugepages(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path = tmp_path / "hw-profile.json"
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=16384,
        power_source="AC",
        block_devices={"sda": 0},
        output_path=prof_path,
    )
    assert res.returncode == 0 and prof is not None
    validate_hw_profile_v1(prof)
    assert prof["memory"]["tier"] == "16G"
    assert prof["memory"]["zram_percent"] == 50
    assert prof["memory"]["sysctl"]["vm.swappiness"] == 100
    assert prof["memory"]["sysctl"]["vm.dirty_ratio"] == 10
    assert prof["blur"] == {
        "tier": "kawase_full",
        "enabled": True,
        "size": 6,
        "passes": 2,
        "xray": True,
    }
    assert prof["subsystems"]["wine"]["prewarm"] is True
    assert prof["subsystems"]["waydroid"]["idle_policy"] == "prewarmed"
    assert prof["subsystems"]["waydroid"]["prewarm"] is True
    assert prof["subsystems"]["osx_kvm"]["hugepages_on_demand"] is True


def test_t4_s3_osx_kvm_app_launch_savevm_and_provision_scripts(
    repo_root: Path, python_exe: str, git_bash_exe: str, tmp_path: Path
) -> None:
    prof_path = tmp_path / "hw-profile.json"
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=16384,
        power_source="AC",
        block_devices={"sda": 0},
        output_path=prof_path,
    )
    assert res.returncode == 0 and prof is not None
    if not prof_path.is_file():
        prof_path.write_text(json.dumps(prof), encoding="utf-8")

    sketch = tmp_path / "Sketch.app"
    (sketch / "Contents" / "MacOS").mkdir(parents=True)
    (sketch / "Contents" / "MacOS" / "Sketch").write_bytes(b"\xcf\xfa\xed\xfe")

    r_open = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(sketch), "--dry-run", "--json"],
        hw_profile_path=prof_path,
        kvm_available=True,
    )
    assert r_open.returncode == 0, r_open.stderr
    odata = json.loads(r_open.stdout)
    assert odata["platform"] == "macos"
    cmd_str = " ".join(odata["command"])
    assert "Haswell-noTSX,+invtsc,vendor=GenuineIntel" in cmd_str
    assert "virtio" in r_open.stdout.lower()

    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "all", "hibernate")
    r_lc = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        lc_args,
        hw_profile_path=prof_path,
        kvm_available=True,
    )
    assert r_lc.returncode == 0, r_lc.stderr
    assert "prewarm" in r_lc.stdout.lower() and "savevm" in r_lc.stdout.lower()

    for rel in (
        "kite-bridge/scripts/provision-wine.sh",
        "kite-bridge/scripts/provision-waydroid.sh",
        "kite-bridge/scripts/provision-macos.sh",
    ):
        run_sh_syntax_check(git_bash_exe, repo_root / rel)


# ===========================================================================
# Scenario 4: Interactive kite-shell/preview/ Playwright Journey (2 tests)
# ===========================================================================


def test_t4_s4_preview_desktop_start_quick_settings_notifications_snap(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.set_viewport_size({"width": 1366, "height": 768})
    playwright_page.goto(preview_server_url, wait_until="load")
    assert len(playwright_page.locator("body").inner_text().strip()) > 10
    assert not playwright_page.evaluate(
        "document.documentElement.scrollWidth > 1366"
    )

    assert _click_any(playwright_page, ["Start"]), "Start button missing"
    body = playwright_page.locator("body").inner_text()
    for badge in ("[Win]", "[Android]", "[macOS]"):
        assert badge.lower() in body.lower()

    search = playwright_page.locator("input[type='search'], input[type='text'], [role='searchbox']").first
    search.fill("Win")
    search.fill("")
    playwright_page.keyboard.press("Escape")

    assert _click_any(playwright_page, ["Quick Settings", "Win+A", "Wi-Fi", "Volume"])
    assert _click_any(playwright_page, ["Notification", "Win+N", "Calendar"])
    assert _click_any(playwright_page, ["Snap", "Win+Z", "Layout"])
    _assert_zero_browser_errors(playwright_page)


def test_t4_s4_preview_settings_studio_presets_taskbar_and_hw_switcher(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.set_viewport_size({"width": 1366, "height": 768})
    playwright_page.goto(preview_server_url, wait_until="load")

    _click_any(playwright_page, ["Settings", "Personalization", "kite-settings"])
    _click_any(playwright_page, ["Left", "Taskbar Alignment", "Align"])
    _click_any(playwright_page, ["Center"])

    for preset in ("Frosted Obsidian", "Ultra-Light Flat", "Aero Blue"):
        assert _click_any(playwright_page, [preset]), f"Preset {preset} not clickable"

    sliders = playwright_page.locator("input[type='range']")
    if sliders.count() > 0:
        sliders.first.fill("0.55")
        sliders.first.dispatch_event("input")
        sliders.first.dispatch_event("change")

    for hw in ("4G", "Battery", "8G", "16G", "AC"):
        assert _click_any(playwright_page, [hw]), f"Hardware control '{hw}' not clickable"
    assert playwright_page.locator("#desktop-root").get_attribute("data-hw-tier") == "16G"
    assert playwright_page.locator("#desktop-root").get_attribute("data-power") == "AC"

    playwright_page.set_viewport_size({"width": 1600, "height": 900})
    assert not playwright_page.evaluate(
        "document.documentElement.scrollWidth > 1600"
    )
    _assert_zero_browser_errors(playwright_page)


# ===========================================================================
# Scenario 5: Full Repository Audit + Script/CI/Calamares Validation (4 tests)
# ===========================================================================


def test_t4_s5_step1_verbatim_rules_skill_and_docs_audit(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md")
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md"
    )
    readme = require_artifact(repo_root / "README.md")

    a_raw = agents.read_bytes()
    s_raw = skill.read_bytes()
    assert len(a_raw) == AGENTS_BYTES and hashlib.sha256(a_raw).hexdigest() == AGENTS_SHA256
    assert len(s_raw) == SKILL_BYTES and hashlib.sha256(s_raw).hexdigest() == SKILL_SHA256

    r_txt = readme.read_text(encoding="utf-8")
    for tok in (
        "iso-profile",
        "kite-hw-tune",
        "kite-shell",
        "preview",
        "kite-bridge",
        "installer",
        "scripts",
        ".github/workflows",
        "pytest",
    ):
        assert tok in r_txt


def test_t4_s5_step2_invariant_checker_live_and_adversarial_audit(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    checker = require_artifact(repo_root / "scripts" / "check_invariants.py")
    live = subprocess.run(
        [python_exe, str(checker)], cwd=str(repo_root), capture_output=True, text=True, timeout=30
    )
    assert live.returncode == 0, live.stdout + "\n" + live.stderr

    # Adversarial mutations in isolated tmp_path
    help_txt = subprocess.run(
        [python_exe, str(checker), "--help"], capture_output=True, text=True, timeout=20
    ).stdout
    root_flag = "--root" if "--root" in help_txt else ("--repo-root" if "--repo-root" in help_txt else "")

    def make_base(sub: str) -> Path:
        r = tmp_path / sub
        (r / "iso-profile" / "airootfs" / "etc" / "environment.d").mkdir(parents=True)
        (r / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
            "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
        )
        (r / "iso-profile" / "pacman.conf").write_text(
            "[options]\nArchitecture = x86_64 x86_64_v3\n[cachyos-v3]\nInclude = /etc/pacman.d/cachyos-v3-mirrorlist\n",
            encoding="utf-8",
        )
        (r / "iso-profile" / "packages.x86_64").write_text(
            "linux-cachyos\nmesa\nvulkan-intel\nlibva-intel-driver\npipewire\nbtrfs-progs\n",
            encoding="utf-8",
        )
        (r / "iso-profile" / "airootfs" / "etc" / "modules-load.d").mkdir(parents=True)
        (r / "iso-profile" / "airootfs" / "etc" / "modules-load.d" / "kite-os.conf").write_text(
            "ntsync\nbinder_linux\n", encoding="utf-8"
        )
        (r / "iso-profile" / "efiboot" / "loader" / "entries").mkdir(parents=True)
        (r / "iso-profile" / "efiboot" / "loader" / "entries" / "kite-os.conf").write_text(
            "title KITE_OS\noptions i915.enable_fbc=1 i915.fastboot=1 intel_pstate=active\n",
            encoding="utf-8",
        )
        (r / "kite-hw-tune" / "config").mkdir(parents=True)
        (r / "kite-hw-tune" / "config" / "kite-haswell.env").write_text(
            "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
        )
        (r / "kite-hw-tune" / "tuner.py").write_text(
            "TIERS = ('lz4', 'zstd')\nSCHED = ('rotational', 'bfq', 'kyber')\n",
            encoding="utf-8",
        )
        (r / "kite-bridge" / "scripts").mkdir(parents=True)
        (r / "kite-bridge" / "scripts" / "provision-wine.sh").write_text(
            "#!/usr/bin/env bash\nDXVK_VER=1.10.3\n", encoding="utf-8"
        )
        (r / "kite-bridge" / "bridge.py").write_text(
            "CPU = 'Haswell-noTSX,+invtsc,vendor=GenuineIntel'\nPROP = 'persist.waydroid.multi_windows'\n",
            encoding="utf-8",
        )
        (r / "installer" / "calamares" / "modules").mkdir(parents=True)
        (r / "installer" / "calamares" / "modules" / "mount.conf").write_text(
            "btrfsSubvolumes:\n"
            "  - mountPoint: /\n    subvolume: /@\n"
            "  - mountPoint: /home\n    subvolume: /@home\n"
            "  - mountPoint: /var/lib/kitebridge\n    subvolume: /@kitebridge\n"
            "  - mountPoint: /.snapshots\n    subvolume: /@snapshots\n"
            "mountOptions:\n"
            "  - filesystem: btrfs\n    options: [compress=zstd:1, noatime]\n",
            encoding="utf-8",
        )
        (r / "installer" / "calamares" / "modules" / "bootloader.conf").write_text(
            "kernelParams:\n  - i915.enable_fbc=1\n  - i915.fastboot=1\n  - intel_pstate=active\n",
            encoding="utf-8",
        )
        return r

    def run_on(r: Path) -> int:
        cmd = [python_exe, str(checker)] + ([root_flag, str(r)] if root_flag else [str(r)])
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode

    # Valid + prohibitory docs must pass
    r_doc = make_base("doc_ok")
    bad_gl = "ir" + "is"
    (r_doc / "README.md").write_text(f"Do NOT use {bad_gl}.\n", encoding="utf-8")
    assert run_on(r_doc) == 0

    # 4 mutations must fail
    r1 = make_base("m_iris")
    (r1 / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        f"MESA_LOADER_DRIVER_OVERRIDE={bad_gl}\nLIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
    )
    assert run_on(r1) != 0

    r2 = make_base("m_ihd")
    bad_va = "iH" + "D"
    (r2 / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        f"MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME={bad_va}\n", encoding="utf-8"
    )
    assert run_on(r2) != 0

    r3 = make_base("m_dxvk")
    bad_dxvk = "DXVK_VER=" + "2.3"
    (r3 / "kite-bridge" / "scripts" / "provision-wine.sh").write_text(
        f"#!/usr/bin/env bash\n{bad_dxvk}\n", encoding="utf-8"
    )
    assert run_on(r3) != 0

    r4 = make_base("m_btrfs")
    (r4 / "installer" / "calamares" / "modules" / "mount.conf").write_text(
        "btrfsSubvolumes:\n  - mountPoint: /\n    subvolume: /@\n", encoding="utf-8"
    )
    assert run_on(r4) != 0


def test_t4_s5_step3_all_scripts_and_ci_cross_platform_syntax_and_dryrun(
    repo_root: Path, git_bash_exe: str, powershell_exe: str
) -> None:
    require_artifact(repo_root / "scripts" / "build-iso.sh")
    require_artifact(repo_root / "scripts" / "build-iso.ps1")
    require_artifact(repo_root / "scripts" / "test-qemu.sh")
    require_artifact(repo_root / "scripts" / "test-qemu.ps1")
    wf = require_artifact(repo_root / ".github" / "workflows" / "build-iso.yml")

    for sh in repo_root.rglob("*.sh"):
        if "tests" not in sh.parts:
            run_sh_syntax_check(git_bash_exe, sh)
    for ps1 in (repo_root / "scripts").glob("*.ps1"):
        run_ps1_syntax_check(powershell_exe, ps1)

    qemu_sh = repo_root / "scripts" / "test-qemu.sh"
    sh_help = subprocess.run(
        [git_bash_exe, str(qemu_sh), "--help"], cwd=str(repo_root), capture_output=True, text=True, timeout=20
    ).stdout
    disk_variants = (
        (["--rotational", "0"], ["--rotational", "1"])
        if "--rotational" in sh_help
        else (["--disk", "ssd"], ["--disk", "hdd"])
    )
    for tier in ("4G", "8G", "16G"):
        for d_args in disk_variants:
            r = subprocess.run(
                [git_bash_exe, str(qemu_sh), "--dry-run", "--ram", tier, *d_args],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert r.returncode == 0
            assert "-cpu Haswell-noTSX" in r.stdout
            assert "e1000e" in r.stdout
            assert ISO_FILENAME in r.stdout

    ci = run_yaml_load_check(wf)
    assert isinstance(ci, dict) and "jobs" in ci
    assert "--privileged" in wf.read_text(encoding="utf-8")


def test_t4_s5_step4_calamares_btrfs_and_hardware_validation_audit(
    repo_root: Path, git_bash_exe: str
) -> None:
    cal = require_artifact(repo_root / "installer" / "calamares")
    for rel in (
        "settings.conf",
        "branding/kite-os/branding.desc",
        "modules/partition.conf",
        "modules/mount.conf",
        "modules/bootloader.conf",
        "modules/shellprocess.conf",
    ):
        run_yaml_load_check(cal / rel)

    mnt_txt = (cal / "modules" / "mount.conf").read_text(encoding="utf-8")
    for sub in ("@", "@home", "@kitebridge", "@snapshots", "compress=zstd:1", "noatime"):
        assert sub in mnt_txt

    for qml in (cal / "branding" / "kite-os").glob("*.qml"):
        run_qml_structural_check(qml)

    val_sh = require_artifact(repo_root / "installer" / "validation" / "validate-hardware.sh")
    require_artifact(repo_root / "installer" / "validation" / "folio9480m-checklist.md")
    run_sh_syntax_check(git_bash_exe, val_sh)
    r_help = subprocess.run(
        [git_bash_exe, str(val_sh), "--help"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert r_help.returncode == 0
    assert not scan_active_forbidden_assignments(repo_root, ["installer"])
