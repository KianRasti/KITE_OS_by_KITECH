"""Tier 3 Pairwise Cross-Feature Combination E2E tests (37 combinations)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import (
    ISO_FILENAME,
    build_kite_bridge_lifecycle_args,
    introspect_cli_help,
    invoke_kite_settings_cli,
    require_artifact,
    run_kite_bridge,
    run_kite_hw_tune,
    run_kite_settings,
    run_yaml_load_check,
    scan_active_forbidden_assignments,
    write_minimal_apk,
)

pytestmark = pytest.mark.tier3


def _emit_hw_profile(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    *,
    ram_mb: int,
    power_source: str,
    block_devices: dict[str, int],
) -> tuple[Path, dict[str, Any]]:
    prof_path = tmp_path / "hw-profile.json"
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=ram_mb,
        power_source=power_source,
        block_devices=block_devices,
        output_path=prof_path,
    )
    assert res.returncode == 0 and prof is not None, res.stderr
    if not prof_path.is_file():
        prof_path.write_text(json.dumps(prof, indent=2), encoding="utf-8")
    return prof_path, prof


def _emit_settings_and_hypr(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    *,
    hw_profile_path: Path,
    autosimplify: bool,
    preset: str = "Aero Blue",
) -> str:
    payload = {
        "schema_version": 1,
        "theme_preset": preset,
        "accent_color": "#38BDF8",
        "taskbar_alignment": "center",
        "transparency": 0.72,
        "blur_radius": 6,
        "specular_edge_brightness": 0.35,
        "corner_radius": 12,
        "animation_speed": 1.0,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "aero-glass-wave",
        "battery_glass_autosimplify": autosimplify,
        "mitigations_off_requested": False,
    }
    res, _, hypr_txt = invoke_kite_settings_cli(
        repo_root,
        python_exe,
        tmp_path,
        settings_dict=payload,
        hw_profile_path=hw_profile_path,
    )
    assert res.returncode == 0, res.stderr
    return hypr_txt


# ===========================================================================
# Spec Miner 1 Cross-Feature Combinations (13 tests)
# ===========================================================================


def test_t3_f1_f2_f8_agents_skill_and_invariant_checker_agree(
    repo_root: Path, python_exe: str
) -> None:
    agents = require_artifact(repo_root / "AGENTS.md").read_text(encoding="utf-8")
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md"
    ).read_text(encoding="utf-8")
    checker = require_artifact(repo_root / "scripts" / "check_invariants.py")
    assert "crocus" in agents and "crocus" in skill
    assert "i965" in agents and "i965" in skill
    assert "1.10.3" in agents and "1.10.3" in skill
    res = subprocess.run(
        [python_exe, str(checker)], cwd=str(repo_root), capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, res.stdout + "\n" + res.stderr


def test_t3_f4_f22_iso_and_calamares_kernel_params_match(repo_root: Path) -> None:
    iso_dir = require_artifact(repo_root / "iso-profile")
    bl_conf = require_artifact(
        repo_root / "installer" / "calamares" / "modules" / "bootloader.conf"
    )
    iso_boot = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (
            list((iso_dir / "efiboot").rglob("*.conf"))
            + list((iso_dir / "grub").rglob("*.cfg"))
            + list((iso_dir / "syslinux").rglob("*.cfg"))
        )
    )
    cal_txt = bl_conf.read_text(encoding="utf-8")
    for param in ("i915.enable_fbc=1", "i915.fastboot=1"):
        assert param in iso_boot and param in cal_txt


def test_t3_f4_f22_iso_and_calamares_no_forbidden_gpu_drivers(repo_root: Path) -> None:
    require_artifact(repo_root / "iso-profile")
    require_artifact(repo_root / "installer" / "calamares")
    assert not scan_active_forbidden_assignments(repo_root, ["iso-profile", "installer/calamares"])


def test_t3_f4_f5_build_script_and_profiledef_iso_name_match(repo_root: Path) -> None:
    pd = require_artifact(repo_root / "iso-profile" / "profiledef.sh").read_text(encoding="utf-8")
    bsh = require_artifact(repo_root / "scripts" / "build-iso.sh").read_text(encoding="utf-8")
    bps = require_artifact(repo_root / "scripts" / "build-iso.ps1").read_text(encoding="utf-8")
    assert "kite-os-folio9480" in pd
    assert ISO_FILENAME in bsh and ISO_FILENAME in bps


def test_t3_f5_f6_f7_iso_artifact_filename_consistent_across_build_qemu_ci(
    repo_root: Path,
) -> None:
    for rel in (
        ".agents/skills/kite-os-builder/SKILL.md",
        "scripts/build-iso.sh",
        "scripts/build-iso.ps1",
        "scripts/test-qemu.sh",
        "scripts/test-qemu.ps1",
        ".github/workflows/build-iso.yml",
    ):
        txt = require_artifact(repo_root / rel).read_text(encoding="utf-8")
        assert ISO_FILENAME in txt, f"{rel} missing canonical ISO name {ISO_FILENAME}"


def test_t3_f6_sh_ps1_qemu_cli_flag_parity(
    repo_root: Path, git_bash_exe: str, powershell_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "test-qemu.sh")
    ps1 = require_artifact(repo_root / "scripts" / "test-qemu.ps1")
    sh_help = subprocess.run(
        [git_bash_exe, str(sh), "--help"], cwd=str(repo_root), capture_output=True, text=True, timeout=20
    ).stdout
    ps1_txt = ps1.read_text(encoding="utf-8")
    use_rot_sh = "--rotational" in sh_help
    use_rot_ps = bool(re.search(r"\$Rotational\b", ps1_txt, re.IGNORECASE))
    for tier, rot_val, disk_mode in (("4G", "0", "ssd"), ("8G", "1", "hdd"), ("16G", "0", "ssd")):
        sh_disk_args = ["--rotational", rot_val] if use_rot_sh else ["--disk", disk_mode]
        ps_disk_args = ["-Rotational", rot_val] if use_rot_ps else ["-Disk", disk_mode]
        r_sh = subprocess.run(
            [git_bash_exe, str(sh), "--dry-run", "--ram", tier, *sh_disk_args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
        )
        r_ps = subprocess.run(
            [
                powershell_exe,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
                "-DryRun",
                "-Ram",
                tier,
                *ps_disk_args,
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r_sh.returncode == 0 and r_ps.returncode == 0
        for out in (r_sh.stdout, r_ps.stdout):
            assert "-cpu Haswell-noTSX" in out
            assert f"-m {tier}" in out
            assert "-smp 4,cores=2,threads=2" in out
            assert "e1000e" in out
            assert "ovmf" in out.lower()


def test_t3_f5_sh_ps1_build_iso_parity(
    repo_root: Path, git_bash_exe: str, powershell_exe: str
) -> None:
    bsh = require_artifact(repo_root / "scripts" / "build-iso.sh")
    bps = require_artifact(repo_root / "scripts" / "build-iso.ps1")
    r_sh = subprocess.run(
        [git_bash_exe, str(bsh), "--dry-run"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    r_ps = subprocess.run(
        [powershell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(bps), "-DryRun"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r_sh.returncode == 0 and r_ps.returncode == 0
    assert ISO_FILENAME in r_sh.stdout and ISO_FILENAME in r_ps.stdout


def test_t3_f7_f8_ci_executes_invariant_checker(
    repo_root: Path, python_exe: str
) -> None:
    wf = require_artifact(repo_root / ".github" / "workflows" / "build-iso.yml").read_text(
        encoding="utf-8"
    )
    checker = require_artifact(repo_root / "scripts" / "check_invariants.py")
    assert "check_invariants.py" in wf
    res = subprocess.run(
        [python_exe, str(checker)], cwd=str(repo_root), capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0


def test_t3_f3_f5_f6_f7_readme_matches_actual_filenames_and_flags(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md").read_text(encoding="utf-8")
    for rel in (
        "scripts/build-iso.sh",
        "scripts/build-iso.ps1",
        "scripts/test-qemu.sh",
        "scripts/test-qemu.ps1",
        "scripts/check_invariants.py",
        ".github/workflows/build-iso.yml",
    ):
        require_artifact(repo_root / rel)
        assert Path(rel).name in readme
    assert "Haswell-noTSX" in readme


def test_t3_f4_f11_iso_env_and_hw_tune_crocus_i965_consistent(repo_root: Path) -> None:
    iso_env = require_artifact(
        repo_root / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf"
    ).read_text(encoding="utf-8")
    tune_cfg = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in require_artifact(repo_root / "kite-hw-tune" / "config").rglob("*")
        if p.is_file()
    )
    for pin in ("MESA_LOADER_DRIVER_OVERRIDE=crocus", "LIBVA_DRIVER_NAME=i965"):
        assert pin in iso_env and pin in tune_cfg


def test_t3_f22_f17_calamares_kitebridge_subvolume_mount_aligned(repo_root: Path) -> None:
    mnt = run_yaml_load_check(
        require_artifact(repo_root / "installer" / "calamares" / "modules" / "mount.conf")
    )
    subvols = {
        s.get("subvolume", "").lstrip("/"): s.get("mountPoint")
        for s in mnt.get("btrfsSubvolumes", [])
        if isinstance(s, dict)
    }
    assert subvols.get("@kitebridge") == "/var/lib/kitebridge"
    bridge_txt = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in require_artifact(repo_root / "kite-bridge").rglob("*")
        if p.is_file()
    )
    assert "/var/lib/kitebridge" in bridge_txt


def test_t3_f22_f23_calamares_layout_and_hardware_validation_agree(repo_root: Path) -> None:
    val_sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh"
    ).read_text(encoding="utf-8")
    cl = require_artifact(
        repo_root / "installer" / "validation" / "folio9480m-checklist.md"
    ).read_text(encoding="utf-8")
    combined = val_sh + "\n" + cl
    for tok in ("@home", "@kitebridge", "@snapshots", "zstd:1", "i915"):
        assert tok in combined


def test_t3_f4_f23_iso_modules_and_hardware_validation_agree(repo_root: Path) -> None:
    require_artifact(repo_root / "iso-profile")
    val_txt = (
        require_artifact(repo_root / "installer" / "validation" / "validate-hardware.sh").read_text(
            encoding="utf-8"
        )
        + "\n"
        + require_artifact(
            repo_root / "installer" / "validation" / "folio9480m-checklist.md"
        ).read_text(encoding="utf-8")
    )
    for tok in ("ntsync", "binder", "iwlwifi", "e1000e", "snd_hda_intel", "Synaptics", "VFS495"):
        assert tok.lower() in val_txt.lower()


# ===========================================================================
# Explorer 1 Pairwise Combinations (14 tests: T3-01 .. T3-14)
# ===========================================================================


def test_t3_01_4g_ac_hdd_android_apk(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="AC", block_devices={"sda": 1}
    )
    assert prof["storage"][0]["scheduler"] == "bfq"
    assert prof["blur"]["tier"] == "static"
    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        lc_args,
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    assert "freeze_then_teardown" in res.stdout and "300" in res.stdout


def test_t3_02_4g_battery_ssd_win_exe(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="Battery", block_devices={"sda": 0}
    )
    assert prof["power"]["snd_hda_intel_power_save"] == 1
    assert prof["storage"][0]["scheduler"] in {"kyber", "none"}
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(exe), "--dry-run", "--json"],
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["dxvk_version"] == "1.10.3"
    assert data["env"]["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"


def test_t3_03_8g_ac_ssd_android_apk(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="AC", block_devices={"sda": 0}
    )
    assert prof["blur"] == {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True}
    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        lc_args,
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    assert "cgroup_freeze" in res.stdout or "freeze" in res.stdout


def test_t3_04_8g_battery_hdd_win_msi(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="Battery", block_devices={"sda": 1}
    )
    assert prof["blur"]["passes"] == 1
    assert prof["power"]["iwlwifi_power_save"] is True
    assert prof["storage"][0]["scheduler"] == "bfq"
    msi = tmp_path / "setup.msi"
    msi.write_bytes(b"MSI")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(msi), "--dry-run", "--json"],
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    assert json.loads(res.stdout)["env"]["DXVK_VER"] == "1.10.3"


def test_t3_05_16g_ac_ssd_win_exe(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="AC", block_devices={"sda": 0}
    )
    assert prof["subsystems"]["wine"]["prewarm"] is True
    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "wine", "status")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        lc_args,
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    assert "prewarm" in res.stdout.lower()


def test_t3_06_16g_ac_ssd_macos_gui_app_kvm_present(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="AC", block_devices={"sda": 0}
    )
    assert prof["subsystems"]["osx_kvm"]["hugepages_on_demand"] is True
    app = tmp_path / "Cocoa.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Cocoa").write_bytes(b"\xcf\xfa\xed\xfe")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(app), "--dry-run", "--json"],
        hw_profile_path=prof_path,
        kvm_available=True,
    )
    assert res.returncode == 0
    cmd_str = " ".join(json.loads(res.stdout)["command"])
    assert "Haswell-noTSX,+invtsc,vendor=GenuineIntel" in cmd_str
    assert "virtio" in res.stdout.lower()


def test_t3_07_16g_battery_hdd_android_aab(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="Battery", block_devices={"sda": 1}
    )
    assert prof["blur"]["passes"] == 1
    assert prof["subsystems"]["waydroid"]["prewarm"] is True
    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        lc_args,
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    assert "prewarm" in res.stdout.lower()


def test_t3_08_8g_ac_mixed_ssd_hdd_macos_dmg(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=8192,
        power_source="AC",
        block_devices={"sda": 0, "sdb": 1},
    )
    by_dev = {d["device"]: d["scheduler"] for d in prof["storage"]}
    assert by_dev["sda"] in {"kyber", "none"} and by_dev["sdb"] == "bfq"
    dmg = tmp_path / "disk.dmg"
    dmg.write_bytes(b"DMG")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["inspect", str(dmg), "--json"],
        hw_profile_path=prof_path,
    )
    assert res.returncode == 0
    assert json.loads(res.stdout)["platform"] == "macos"


def test_t3_09_16g_battery_ssd_macos_gui_app_kvm_absent(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="Battery", block_devices={"sda": 0}
    )
    app = tmp_path / "Cocoa.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Cocoa").write_bytes(b"\xcf\xfa\xed\xfe")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(app), "--dry-run", "--json"],
        hw_profile_path=prof_path,
        kvm_available=False,
    )
    assert "Traceback" not in res.stderr
    assert "kvm" in (res.stdout + res.stderr).lower()


def test_t3_10_4g_ac_ssd_macos_cli_macho_kvm_absent(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="AC", block_devices={"sda": 0}
    )
    macho = tmp_path / "cli.macho"
    macho.write_bytes(b"\xcf\xfa\xed\xfe")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(macho), "--dry-run", "--json"],
        hw_profile_path=prof_path,
        kvm_available=False,
    )
    assert res.returncode == 0
    assert "darling" in json.loads(res.stdout)["handler"].lower()


def test_t3_11_desktop_tags_match_start_menu_parser(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    sm_txt = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml"
    ).read_text(encoding="utf-8")
    exe = tmp_path / "WinApp.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["install", str(exe)])
    assert res.returncode == 0
    desk = list(tmp_path.rglob("kitebridge-*.desktop"))
    assert desk
    dtxt = desk[0].read_text(encoding="utf-8")
    assert "X-KiteBridge-Platform=win" in dtxt and "[Win]" in dtxt
    assert "[Win]" in sm_txt or "X-KiteBridge-Platform" in sm_txt or "win" in sm_txt.lower()


def test_t3_12_hw_tune_and_bridge_crocus_i965_consistent(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    tune_cfg = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in require_artifact(repo_root / "kite-hw-tune" / "config").rglob("*")
        if p.is_file()
    )
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["open", str(exe), "--dry-run", "--json"]
    )
    assert res.returncode == 0
    env = json.loads(res.stdout)["env"]
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in tune_cfg
    assert env["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert "LIBVA_DRIVER_NAME=i965" in tune_cfg
    assert env["LIBVA_DRIVER_NAME"] == "i965"


def test_t3_13_hw_tune_profile_blur_matches_hypr_runtime_bounds(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, prof = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="Battery", block_devices={"sda": 0}
    )
    hypr_txt = _emit_settings_and_hypr(
        repo_root, python_exe, tmp_path, hw_profile_path=prof_path, autosimplify=True
    )
    assert prof["blur"]["passes"] == 1
    assert re.search(r"passes\s*=\s*1\b", hypr_txt)


def test_t3_14_mime_xml_desktop_provision_scripts_aligned(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    mime = require_artifact(
        repo_root / "kite-bridge" / "mime" / "kitebridge-mime.xml"
    ).read_text(encoding="utf-8").lower()
    prov_txt = "\n".join(
        require_artifact(repo_root / "kite-bridge" / "scripts" / s).read_text(encoding="utf-8")
        for s in ("provision-wine.sh", "provision-waydroid.sh", "provision-macos.sh")
    ).lower()
    for ext, plat, kw in (
        ("app.exe", "win", "dxvk"),
        ("app.apk", "android", "waydroid"),
        ("disk.dmg", "macos", "darling"),
    ):
        assert ext.split(".")[1] in mime
        assert kw in prov_txt
        f = tmp_path / ext
        if ext.endswith(".apk"):
            write_minimal_apk(f)
        else:
            f.write_bytes(b"DUMMY")
        res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(f), "--json"])
        assert res.returncode == 0 and json.loads(res.stdout)["platform"] == plat


# ===========================================================================
# Explorer 2 Shell/Settings/Preview Combinations (10 tests)
# ===========================================================================


def test_t3_shell_01_4g_ac_autosimplify_true_forces_blur_off(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="AC", block_devices={"sda": 0}
    )
    hypr_txt = _emit_settings_and_hypr(
        repo_root, python_exe, tmp_path, hw_profile_path=prof_path, autosimplify=True
    )
    assert re.search(r"enabled\s*=\s*false", hypr_txt, re.IGNORECASE) or re.search(
        r"passes\s*=\s*0\b", hypr_txt
    )


def test_t3_shell_02_4g_battery_autosimplify_false_still_forces_blur_off(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=4096, power_source="Battery", block_devices={"sda": 0}
    )
    hypr_txt = _emit_settings_and_hypr(
        repo_root, python_exe, tmp_path, hw_profile_path=prof_path, autosimplify=False
    )
    assert re.search(r"enabled\s*=\s*false", hypr_txt, re.IGNORECASE) or re.search(
        r"passes\s*=\s*0\b", hypr_txt
    )


def test_t3_shell_03_8g_ac_autosimplify_true_2pass(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="AC", block_devices={"sda": 0}
    )
    hypr_txt = _emit_settings_and_hypr(
        repo_root, python_exe, tmp_path, hw_profile_path=prof_path, autosimplify=True
    )
    assert re.search(r"enabled\s*=\s*true", hypr_txt, re.IGNORECASE)
    assert re.search(r"size\s*=\s*6\b", hypr_txt)
    assert re.search(r"passes\s*=\s*2\b", hypr_txt)
    assert re.search(r"xray\s*=\s*true", hypr_txt, re.IGNORECASE)


def test_t3_shell_04_8g_battery_autosimplify_true_1pass(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="Battery", block_devices={"sda": 0}
    )
    hypr_txt = _emit_settings_and_hypr(
        repo_root, python_exe, tmp_path, hw_profile_path=prof_path, autosimplify=True
    )
    assert re.search(r"passes\s*=\s*1\b", hypr_txt)


def test_t3_shell_05_16g_battery_autosimplify_true_1pass(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof_path, _ = _emit_hw_profile(
        repo_root, python_exe, tmp_path, ram_mb=16384, power_source="Battery", block_devices={"sda": 0}
    )
    hypr_txt = _emit_settings_and_hypr(
        repo_root, python_exe, tmp_path, hw_profile_path=prof_path, autosimplify=True
    )
    assert re.search(r"passes\s*=\s*1\b", hypr_txt)


def test_t3_shell_06_16g_ac_ultralight_vs_aero_blue(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    d1 = tmp_path / "aero"
    d2 = tmp_path / "flat"
    d1.mkdir()
    d2.mkdir()
    p1, _ = _emit_hw_profile(
        repo_root, python_exe, d1, ram_mb=16384, power_source="AC", block_devices={"sda": 0}
    )
    p2, _ = _emit_hw_profile(
        repo_root, python_exe, d2, ram_mb=16384, power_source="AC", block_devices={"sda": 0}
    )
    h_aero = _emit_settings_and_hypr(
        repo_root, python_exe, d1, hw_profile_path=p1, autosimplify=False, preset="Aero Blue"
    )
    h_flat = _emit_settings_and_hypr(
        repo_root, python_exe, d2, hw_profile_path=p2, autosimplify=False, preset="Ultra-Light Flat"
    )
    assert re.search(r"passes\s*=\s*2\b", h_aero)
    assert (
        re.search(r"enabled\s*=\s*false", h_flat, re.IGNORECASE)
        or re.search(r"passes\s*=\s*0\b", h_flat)
        or re.search(r"size\s*=\s*0\b", h_flat)
    )


def test_t3_shell_07_win_desktop_matches_startmenu_qml(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    sm_txt = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml"
    ).read_text(encoding="utf-8")
    f = tmp_path / "WinTool.exe"
    f.write_bytes(b"MZ")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["install", str(f)])
    assert res.returncode == 0
    desk = list(tmp_path.rglob("kitebridge-*.desktop"))[0].read_text(encoding="utf-8")
    assert "X-KiteBridge-Platform=win" in desk and "[Win]" in desk
    assert "[Win]" in sm_txt or "win" in sm_txt.lower()


def test_t3_shell_08_android_desktop_matches_startmenu_qml(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    sm_txt = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml"
    ).read_text(encoding="utf-8")
    f = write_minimal_apk(tmp_path / "AndroidApp.apk")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["install", str(f)])
    assert res.returncode == 0
    desk = list(tmp_path.rglob("kitebridge-*.desktop"))[0].read_text(encoding="utf-8")
    assert "X-KiteBridge-Platform=android" in desk and "[Android]" in desk
    assert "[Android]" in sm_txt or "android" in sm_txt.lower()


def test_t3_shell_09_macos_desktop_matches_startmenu_qml(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    sm_txt = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml"
    ).read_text(encoding="utf-8")
    app = tmp_path / "MacApp.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "MacApp").write_bytes(b"\xcf\xfa\xed\xfe")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["install", str(app)])
    assert res.returncode == 0
    desk = list(tmp_path.rglob("kitebridge-*.desktop"))[0].read_text(encoding="utf-8")
    assert "X-KiteBridge-Platform=macos" in desk and "[macOS]" in desk
    assert "[macOS]" in sm_txt or "macos" in sm_txt.lower()


def test_t3_shell_10_hypr_runtime_source_and_preview_presets_aligned(repo_root: Path) -> None:
    hconf = require_artifact(
        repo_root / "kite-shell" / "hypr" / "hyprland.conf"
    ).read_text(encoding="utf-8")
    assert "kite-glass-runtime.conf" in hconf
    preview_txt = (
        require_artifact(repo_root / "kite-shell" / "preview" / "index.html").read_text(
            encoding="utf-8"
        )
        + "\n"
        + require_artifact(repo_root / "kite-shell" / "preview" / "app.js").read_text(
            encoding="utf-8"
        )
    )
    for preset in (
        "Aero Blue",
        "Frosted Obsidian",
        "Emerald Glass",
        "Sunset Mica",
        "Ultra-Light Flat",
    ):
        assert preset in preview_txt
