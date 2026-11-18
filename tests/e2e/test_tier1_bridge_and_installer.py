"""Tier 1 Category-Partition E2E tests for Features 17–23 (KiteBridge & Installer)."""
from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import (
    build_kite_bridge_lifecycle_args,
    introspect_cli_help,
    require_artifact,
    run_kite_bridge,
    run_qml_structural_check,
    run_sh_syntax_check,
    run_yaml_load_check,
    scan_active_forbidden_assignments,
    validate_bridge_inspect_json,
    write_minimal_aab,
    write_minimal_apk,
)

pytestmark = pytest.mark.tier1


def _write_hw_profile(tmp_path: Path, tier: str) -> Path:
    profiles: dict[str, dict[str, Any]] = {
        "4G": {
            "schema_version": 1,
            "ram_mb": 4096,
            "memory": {
                "tier": "4G",
                "zram_percent": 150,
                "zram_size_mb": 6144,
                "zram_algo": "lz4",
                "idle_budget_mb": 250,
                "sysctl": {
                    "vm.swappiness": 180,
                    "vm.page-cluster": 0,
                    "vm.watermark_boost_factor": 0,
                },
            },
            "power": {
                "source": "Battery",
                "epp": "balance_power",
                "snd_hda_intel_power_save": 1,
                "iwlwifi_power_save": True,
            },
            "blur": {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False},
            "storage": [{"device": "sda", "rotational": 1, "scheduler": "bfq"}],
            "subsystems": {
                "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
                "waydroid": {
                    "idle_policy": "freeze_then_teardown",
                    "teardown_after_sec": 300,
                    "prewarm": False,
                },
                "osx_kvm": {"hugepages_on_demand": False},
            },
        },
        "8G": {
            "schema_version": 1,
            "ram_mb": 8192,
            "memory": {
                "tier": "8G",
                "zram_percent": 100,
                "zram_size_mb": 8192,
                "zram_algo": "zstd",
                "idle_budget_mb": 350,
                "sysctl": {
                    "vm.swappiness": 150,
                    "vm.page-cluster": 0,
                    "vm.vfs_cache_pressure": 75,
                },
            },
            "power": {
                "source": "AC",
                "epp": "balance_performance",
                "snd_hda_intel_power_save": 0,
                "iwlwifi_power_save": False,
            },
            "blur": {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True},
            "storage": [{"device": "sda", "rotational": 0, "scheduler": "kyber"}],
            "subsystems": {
                "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
                "waydroid": {
                    "idle_policy": "cgroup_freeze",
                    "teardown_after_sec": None,
                    "prewarm": False,
                },
                "osx_kvm": {"hugepages_on_demand": False},
            },
        },
        "16G": {
            "schema_version": 1,
            "ram_mb": 16384,
            "memory": {
                "tier": "16G",
                "zram_percent": 50,
                "zram_size_mb": 8192,
                "zram_algo": "zstd",
                "idle_budget_mb": 480,
                "sysctl": {
                    "vm.swappiness": 100,
                    "vm.page-cluster": 0,
                    "vm.dirty_ratio": 10,
                },
            },
            "power": {
                "source": "AC",
                "epp": "balance_performance",
                "snd_hda_intel_power_save": 0,
                "iwlwifi_power_save": False,
            },
            "blur": {"tier": "kawase_full", "enabled": True, "size": 6, "passes": 2, "xray": True},
            "storage": [{"device": "sda", "rotational": 0, "scheduler": "kyber"}],
            "subsystems": {
                "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": True},
                "waydroid": {
                    "idle_policy": "prewarmed",
                    "teardown_after_sec": None,
                    "prewarm": True,
                },
                "osx_kvm": {"hugepages_on_demand": True},
            },
        },
    }
    p = tmp_path / f"hw-profile-{tier}.json"
    p.write_text(json.dumps(profiles[tier], indent=2), encoding="utf-8")
    return p


def _make_dummy_samples(tmp_path: Path) -> dict[str, Path]:
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for name in (
        "app.exe",
        "setup.msi",
        "run.bat",
        "launch.lnk",
        "disk.dmg",
        "inst.pkg",
    ):
        p = samples_dir / name
        p.write_bytes(b"KITE_DUMMY_SAMPLE")
        files[name] = p

    files["app.apk"] = write_minimal_apk(samples_dir / "app.apk")
    files["bundle.aab"] = write_minimal_aab(samples_dir / "bundle.aab")
    macho = samples_dir / "cli_tool.macho"
    macho.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 28)
    files["cli_tool.macho"] = macho

    app_bundle = samples_dir / "Sample.app"
    (app_bundle / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (app_bundle / "Contents" / "Info.plist").write_text(
        "<plist><dict><key>CFBundleExecutable</key><string>Sample</string></dict></plist>",
        encoding="utf-8",
    )
    (app_bundle / "Contents" / "MacOS" / "Sample").write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 28)
    files["Sample.app"] = app_bundle
    return files


# ===========================================================================
# Feature 17: kite-bridge Unified CLI, MIME & Desktop Integration (7 tests)
# ===========================================================================


def test_t1_f17_inspect_and_open_dry_run_json(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    for key in ("app.exe", "app.apk", "disk.dmg"):
        res_i = run_kite_bridge(
            repo_root, python_exe, tmp_path, ["inspect", str(samples[key]), "--json"]
        )
        assert res_i.returncode == 0, f"inspect {key} failed: {res_i.stderr}"
        payload_i = json.loads(res_i.stdout)
        validate_bridge_inspect_json(payload_i)

        res_o = run_kite_bridge(
            repo_root,
            python_exe,
            tmp_path,
            ["open", str(samples[key]), "--dry-run", "--json"],
        )
        assert res_o.returncode == 0, f"open --dry-run {key} failed: {res_o.stderr}"
        payload_o = json.loads(res_o.stdout)
        validate_bridge_inspect_json(payload_o)


def test_t1_f17_list_status_lifecycle_setup_cli(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof = _write_hw_profile(tmp_path, "8G")
    samples = _make_dummy_samples(tmp_path)
    res_inst = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["install", str(samples["app.exe"]), "--json"], hw_profile_path=prof
    )
    assert res_inst.returncode == 0, res_inst.stderr

    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "all", "status")
    for args in (
        ["list", "--json"],
        ["status", "--json"],
        lc_args,
        ["setup", "--dry-run", "--json"],
    ):
        res = run_kite_bridge(
            repo_root, python_exe, tmp_path, args, hw_profile_path=prof
        )
        assert res.returncode == 0, f"kite-bridge {args} failed: {res.stderr}"
        data = json.loads(res.stdout)
        assert isinstance(data, (dict, list)) and len(data) > 0


def test_t1_f17_mime_xml_valid_and_coverage(repo_root: Path) -> None:
    mime_xml = require_artifact(
        repo_root / "kite-bridge" / "mime" / "kitebridge-mime.xml",
        "kitebridge-mime.xml",
    )
    tree = ET.parse(str(mime_xml))
    root = tree.getroot()
    assert "mime-info" in root.tag
    raw_text = mime_xml.read_text(encoding="utf-8").lower()
    for ext in (".exe", ".msi", ".bat", ".lnk", ".apk", ".aab", ".dmg", ".pkg", ".app"):
        assert ext in raw_text, f"kitebridge-mime.xml missing glob for {ext}"


def test_t1_f17_desktop_generation_with_platform_tags(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    help_info = introspect_cli_help(repo_root, python_exe, "kite_bridge", "install")
    desktop_dir = tmp_path / "xdg_data" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    for fname, plat, badge in (
        ("app.exe", "win", "[Win]"),
        ("app.apk", "android", "[Android]"),
        ("Sample.app", "macos", "[macOS]"),
    ):
        args = ["install", str(samples[fname])]
        if "--desktop-dir" in help_info["flags"]:
            args.extend(["--desktop-dir", str(desktop_dir)])
        if "--json" in help_info["flags"]:
            args.append("--json")
        res = run_kite_bridge(repo_root, python_exe, tmp_path, args)
        assert res.returncode == 0, f"install {fname} failed: {res.stderr}"

    desktop_files = list(desktop_dir.glob("kitebridge-*.desktop")) + list(
        (tmp_path / "home" / ".local" / "share" / "applications").glob("kitebridge-*.desktop")
    )
    assert len(desktop_files) >= 3, f"Expected >=3 .desktop files, found {desktop_files}"
    combined = "\n".join(p.read_text(encoding="utf-8") for p in desktop_files)
    assert "[Desktop Entry]" in combined
    assert "X-KiteBridge-Platform=win" in combined
    assert "X-KiteBridge-Platform=android" in combined
    assert "X-KiteBridge-Platform=macos" in combined
    assert "[Win]" in combined and "[Android]" in combined and "[macOS]" in combined


def test_t1_f17_icon_extraction_and_path_integration(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    help_info = introspect_cli_help(repo_root, python_exe, "kite_bridge", "install")
    desktop_dir = tmp_path / "xdg_data" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    args = ["install", str(samples["app.exe"])]
    if "--desktop-dir" in help_info["flags"]:
        args.extend(["--desktop-dir", str(desktop_dir)])
    res = run_kite_bridge(repo_root, python_exe, tmp_path, args)
    assert res.returncode == 0, res.stderr
    desktop_files = list(desktop_dir.glob("kitebridge-*.desktop")) + list(
        (tmp_path / "home" / ".local" / "share" / "applications").glob("kitebridge-*.desktop")
    )
    assert desktop_files
    content = desktop_files[0].read_text(encoding="utf-8")
    assert re.search(r"^Icon=.+", content, re.MULTILINE)


def test_t1_f17_glass_installer_wizard_files_valid(repo_root: Path) -> None:
    mime_dir = require_artifact(repo_root / "kite-bridge" / "mime", "kite-bridge/mime")
    wizard_files = [
        p
        for p in mime_dir.rglob("*")
        if p.is_file() and ("wizard" in p.name.lower() or p.suffix in {".qml", ".html", ".desktop"})
    ]
    assert wizard_files, "Missing Glass Installer Wizard artifacts in kite-bridge/mime/"
    for q in wizard_files:
        if q.suffix == ".qml":
            run_qml_structural_check(q)
    assert not scan_active_forbidden_assignments(repo_root, ["kite-bridge/mime"])


def test_t1_f17_desktop_mime_handler_template(repo_root: Path) -> None:
    mime_dir = require_artifact(repo_root / "kite-bridge" / "mime", "kite-bridge/mime")
    desktop_templates = list(mime_dir.rglob("*.desktop*"))
    assert desktop_templates, "No .desktop template found in kite-bridge/mime/"
    text = "\n".join(p.read_text(encoding="utf-8") for p in desktop_templates)
    assert "[Desktop Entry]" in text
    assert "Exec=" in text and "kite-bridge" in text
    assert "MimeType=" in text


# ===========================================================================
# Feature 18: Windows Subsystem (wine + DXVK 1.10.3) (6 tests)
# ===========================================================================


def test_t1_f18_windows_extensions_routing(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    for fname in ("app.exe", "setup.msi", "run.bat", "launch.lnk"):
        res = run_kite_bridge(
            repo_root, python_exe, tmp_path, ["inspect", str(samples[fname]), "--json"]
        )
        assert res.returncode == 0, f"inspect {fname} failed: {res.stderr}"
        data = json.loads(res.stdout)
        assert data["platform"] == "win"
        assert data["dxvk_version"] == "1.10.3"
        assert "wine" in data["handler"].lower()
        cmd_str = " ".join(data["command"]).lower()
        if fname.endswith(".msi"):
            assert "msiexec" in cmd_str or "wine" in cmd_str
        elif fname.endswith(".bat"):
            assert "cmd" in cmd_str or "wine" in cmd_str
        else:
            assert "wine" in cmd_str


def test_t1_f18_strict_dxvk_1_10_3_and_gpu_env_pins(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["open", str(samples["app.exe"]), "--dry-run", "--json"]
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["dxvk_version"] == "1.10.3"
    assert data["env"]["DXVK_VER"] == "1.10.3"
    assert data["env"]["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert data["env"]["LIBVA_DRIVER_NAME"] == "i965"


def test_t1_f18_dxvk_dll_overrides(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["open", str(samples["app.exe"]), "--dry-run", "--json"]
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    overrides = data["env"].get("WINEDLLOVERRIDES", "") + json.dumps(data)
    for dll in ("d3d9", "d3d10core", "d3d11", "dxgi"):
        assert dll in overrides, f"Missing DXVK override for {dll}"


def test_t1_f18_dx12_routed_to_wined3d_crocus(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["inspect", str(samples["app.exe"]), "--json"]
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data.get("wined3d_dx12") is True
    assert "vkd3d-proton" not in json.dumps(data).lower()
    assert data["env"].get("MESA_LOADER_DRIVER_OVERRIDE") == "crocus"


def test_t1_f18_dev_ntsync_support_flag(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["inspect", str(samples["app.exe"]), "--json"],
        ntsync_available=True,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert "ntsync" in data["handler"].lower() or data.get("ntsync") is True


def test_t1_f18_home_folder_mapping_plan(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["setup", "--dry-run", "--json"]
    )
    assert res.returncode == 0, res.stderr
    assert "wine/prefixes" in res.stdout.lower()
    prov_wine = require_artifact(
        repo_root / "kite-bridge" / "scripts" / "provision-wine.sh", "provision-wine.sh"
    ).read_text(encoding="utf-8")
    combined = (res.stdout + "\n" + prov_wine).lower()
    for folder in ("desktop", "documents", "downloads"):
        assert folder in combined, f"Wine prefix setup/provisioning missing ~/{folder} mapping"


# ===========================================================================
# Feature 19: Android Subsystem (waydroid + RAM Lifecycle) (6 tests)
# ===========================================================================


def test_t1_f19_apk_and_aab_routing(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    for fname in ("app.apk", "bundle.aab"):
        res = run_kite_bridge(
            repo_root, python_exe, tmp_path, ["inspect", str(samples[fname]), "--json"]
        )
        assert res.returncode == 0, f"inspect {fname} failed: {res.stderr}"
        data = json.loads(res.stdout)
        assert data["platform"] == "android"
        assert "waydroid" in data["handler"].lower()
        assert "waydroid" in " ".join(data["command"]).lower()


def test_t1_f19_multi_window_and_kernel_abi_config(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res_setup = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["setup", "--dry-run", "--json"]
    )
    res_insp = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["inspect", str(samples["app.apk"]), "--json"]
    )
    assert res_setup.returncode == 0 and res_insp.returncode == 0
    combined = (res_setup.stdout + "\n" + res_insp.stdout).lower()
    assert "persist.waydroid.multi_windows" in combined
    assert "binder" in combined
    assert "libndk" in combined or "libhoudini" in combined
    insp = json.loads(res_insp.stdout)
    assert insp["env"].get("MESA_LOADER_DRIVER_OVERRIDE") == "crocus"
    assert insp["env"].get("LIBVA_DRIVER_NAME") == "i965"


def test_t1_f19_4g_ram_lifecycle_freeze_then_teardown_300s(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof = _write_hw_profile(tmp_path, "4G")
    args = build_kite_bridge_lifecycle_args(
        repo_root, python_exe, "waydroid", "idle-tick", idle_seconds=300
    )
    res = run_kite_bridge(repo_root, python_exe, tmp_path, args, hw_profile_path=prof)
    assert res.returncode == 0, res.stderr
    txt = res.stdout.lower()
    assert "freeze_then_teardown" in txt
    assert "300" in txt


def test_t1_f19_8g_ram_lifecycle_cgroup_v2_freeze(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof = _write_hw_profile(tmp_path, "8G")
    args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, args, hw_profile_path=prof)
    assert res.returncode == 0, res.stderr
    txt = res.stdout.lower()
    assert "cgroup_freeze" in txt or "freeze" in txt


def test_t1_f19_16g_ram_lifecycle_prewarmed(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof = _write_hw_profile(tmp_path, "16G")
    args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, args, hw_profile_path=prof)
    assert res.returncode == 0, res.stderr
    txt = res.stdout.lower()
    assert "prewarm" in txt


def test_t1_f19_waydroid_status_offline(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["status", "--json"])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert "waydroid" in json.dumps(data).lower()


# ===========================================================================
# Feature 20: macOS Subsystem (darling-dmg + darling + OSX-KVM) (7 tests)
# ===========================================================================


def test_t1_f20_native_volume_routing_dmg_pkg_apfs_hfs(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res_dmg = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["inspect", str(samples["disk.dmg"]), "--json"]
    )
    res_pkg = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["inspect", str(samples["inst.pkg"]), "--json"]
    )
    assert res_dmg.returncode == 0 and res_pkg.returncode == 0
    dmg = json.loads(res_dmg.stdout)
    pkg = json.loads(res_pkg.stdout)
    assert dmg["platform"] == "macos"
    assert pkg["platform"] == "macos"
    assert "darling-dmg" in json.dumps(dmg).lower() or "mount" in json.dumps(dmg).lower()

    # Verify apfs-fuse & hfsprogs referenced in macOS bridge routing and status
    apfs = tmp_path / "samples" / "vol.apfs"
    apfs.write_bytes(b"\x00" * 0x20 + b"NXSB" + b"\x00" * 32)
    hfs = tmp_path / "samples" / "vol.hfs"
    hfs.write_bytes(b"\x00" * 1024 + b"H+" + b"\x00" * 32)
    res_apfs = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(apfs), "--json"])
    res_hfs = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(hfs), "--json"])
    res_status = run_kite_bridge(repo_root, python_exe, tmp_path, ["status", "--json"])
    assert res_apfs.returncode == 0 and res_hfs.returncode == 0 and res_status.returncode == 0
    assert "apfs-fuse" in res_apfs.stdout.lower()
    assert "hfs" in res_hfs.stdout.lower()
    status_txt = res_status.stdout.lower()
    assert "apfs_fuse" in status_txt and "hfs" in status_txt


def test_t1_f20_tier1_cli_macho_via_darling(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["inspect", str(samples["cli_tool.macho"]), "--json"]
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["platform"] == "macos"
    assert "darling" in data["handler"].lower()
    assert "darling" in " ".join(data["command"]).lower()
    assert "qemu" not in " ".join(data["command"]).lower()


def test_t1_f20_tier2_cocoa_gui_osx_kvm_haswell_flags(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(samples["Sample.app"]), "--dry-run", "--json"],
        kvm_available=True,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["platform"] == "macos"
    cmd_str = " ".join(data["command"])
    assert "Haswell-noTSX,+invtsc,vendor=GenuineIntel" in cmd_str


def test_t1_f20_osx_kvm_virtio_fs_home_sharing(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(samples["Sample.app"]), "--dry-run", "--json"],
        kvm_available=True,
    )
    assert res.returncode == 0, res.stderr
    combined = res.stdout.lower()
    assert "virtio-fs" in combined or "virtiofs" in combined


def test_t1_f20_osx_kvm_seamless_window_forwarding(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(samples["Sample.app"]), "--dry-run", "--json"],
        kvm_available=True,
    )
    assert res.returncode == 0, res.stderr
    txt = res.stdout.lower()
    assert any(k in txt for k in ("vnc", "remoteapp", "forward", "spice", "display"))


def test_t1_f20_osx_kvm_idle_hibernate_savevm(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    prof = _write_hw_profile(tmp_path, "16G")
    args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "osx-kvm", "hibernate")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        args,
        hw_profile_path=prof,
    )
    assert res.returncode == 0, res.stderr
    assert "savevm" in res.stdout.lower()


def test_t1_f20_osx_kvm_dev_kvm_preflight_check(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["status", "--json"])
    assert res.returncode == 0, res.stderr
    assert "kvm" in res.stdout.lower()


# ===========================================================================
# Feature 21: kite-bridge Provisioning & Offline Test Mocks (5 tests)
# ===========================================================================


def test_t1_f21_all_provisioning_and_install_scripts_bash_syntax(
    repo_root: Path, git_bash_exe: str
) -> None:
    bridge_dir = require_artifact(repo_root / "kite-bridge", "kite-bridge")
    for rel in (
        "install.sh",
        "scripts/provision-wine.sh",
        "scripts/provision-waydroid.sh",
        "scripts/provision-macos.sh",
    ):
        run_sh_syntax_check(git_bash_exe, bridge_dir / rel)


def test_t1_f21_provision_wine_pins_dxvk_1_10_3_and_checksum(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "kite-bridge" / "scripts" / "provision-wine.sh",
        "provision-wine.sh",
    )
    text = sh.read_text(encoding="utf-8")
    assert "1.10.3" in text
    assert "sha256" in text.lower()
    assert not scan_active_forbidden_assignments(repo_root, ["kite-bridge/scripts"])


def test_t1_f21_provision_waydroid_multi_window_and_abi(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "kite-bridge" / "scripts" / "provision-waydroid.sh",
        "provision-waydroid.sh",
    )
    text = sh.read_text(encoding="utf-8")
    assert "persist.waydroid.multi_windows" in text
    assert "libndk" in text or "libhoudini" in text


def test_t1_f21_provision_macos_covers_darling_apfs_osx_kvm(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "kite-bridge" / "scripts" / "provision-macos.sh",
        "provision-macos.sh",
    )
    text = sh.read_text(encoding="utf-8")
    for tok in ("darling", "darling-dmg", "apfs-fuse", "Haswell-noTSX"):
        assert tok in text, f"provision-macos.sh missing {tok}"


def test_t1_f21_full_offline_cli_execution_on_windows(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    samples = _make_dummy_samples(tmp_path)
    prof = _write_hw_profile(tmp_path, "8G")
    lc_args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "all", "status")
    for args in (
        ["inspect", str(samples["app.exe"]), "--json"],
        ["open", str(samples["app.exe"]), "--dry-run", "--json"],
        ["list", "--json"],
        ["status", "--json"],
        lc_args,
    ):
        res = run_kite_bridge(
            repo_root, python_exe, tmp_path, args, hw_profile_path=prof
        )
        assert res.returncode == 0, f"Offline Windows CLI failed for {args}: {res.stderr}"


# ===========================================================================
# Feature 22: Calamares Glass Installer & Btrfs Layout (6 tests)
# ===========================================================================


def test_f22_calamares_yaml_configs_parse_cleanly(repo_root: Path) -> None:
    cal_dir = require_artifact(repo_root / "installer" / "calamares", "installer/calamares")
    for rel in (
        "settings.conf",
        "branding/kite-os/branding.desc",
        "modules/partition.conf",
        "modules/mount.conf",
        "modules/bootloader.conf",
        "modules/shellprocess.conf",
    ):
        data = run_yaml_load_check(cal_dir / rel)
        assert isinstance(data, dict), f"Expected dict YAML in {rel}"


def test_f22_settings_conf_sequence_and_kite_os_branding(repo_root: Path) -> None:
    settings_path = require_artifact(
        repo_root / "installer" / "calamares" / "settings.conf",
        "calamares/settings.conf",
    )
    data = run_yaml_load_check(settings_path)
    assert data.get("branding") == "kite-os"
    seq_str = json.dumps(data.get("sequence", []))
    for step in ("partition", "mount", "bootloader", "shellprocess"):
        assert step in seq_str, f"Missing Calamares sequence step: {step}"
    assert "unpackfs" in seq_str or "unsquashfs" in seq_str


def test_f22_glass_theme_branding_and_qss_qml(
    repo_root: Path, git_bash_exe: str
) -> None:
    brand_dir = require_artifact(
        repo_root / "installer" / "calamares" / "branding" / "kite-os",
        "calamares branding kite-os",
    )
    bdesc = run_yaml_load_check(brand_dir / "branding.desc")
    assert bdesc.get("componentName") == "kite-os"
    style_files = list(brand_dir.glob("*.qss")) + list(brand_dir.glob("*.qml"))
    assert style_files, "Missing Glass QSS/QML branding files"
    for q in brand_dir.glob("*.qml"):
        run_qml_structural_check(q)
    run_sh_syntax_check(git_bash_exe, repo_root / "installer" / "install.sh")


def test_f22_partition_conf_btrfs_default(repo_root: Path) -> None:
    part = require_artifact(
        repo_root / "installer" / "calamares" / "modules" / "partition.conf",
        "partition.conf",
    )
    data = run_yaml_load_check(part)
    assert data.get("defaultFileSystemType") == "btrfs"


def test_f22_mount_conf_exact_subvolumes_and_zstd1_noatime(repo_root: Path) -> None:
    mnt = require_artifact(
        repo_root / "installer" / "calamares" / "modules" / "mount.conf",
        "mount.conf",
    )
    data = run_yaml_load_check(mnt)
    subvols = data.get("btrfsSubvolumes", [])
    assert isinstance(subvols, list) and len(subvols) >= 4
    mapping = {
        item.get("subvolume", "").lstrip("/"): item.get("mountPoint")
        for item in subvols
        if isinstance(item, dict)
    }
    assert mapping.get("@") == "/"
    assert mapping.get("@home") == "/home"
    assert mapping.get("@kitebridge") == "/var/lib/kitebridge"
    assert mapping.get("@snapshots") == "/.snapshots"

    mount_options = data.get("mountOptions", [])
    assert isinstance(mount_options, list) and mount_options, "mountOptions must be a non-empty list"
    btrfs_entries = [
        item
        for item in mount_options
        if isinstance(item, dict) and item.get("filesystem") == "btrfs"
    ]
    assert len(btrfs_entries) == 1, f"Expected exactly 1 btrfs entry in mountOptions, got {btrfs_entries}"
    btrfs_entry = btrfs_entries[0]
    btrfs_opts = btrfs_entry.get("options", [])
    assert isinstance(btrfs_opts, list) and btrfs_opts, f"Invalid btrfs options: {btrfs_opts}"
    assert "compress=zstd:1" in btrfs_opts, f"btrfs options missing compress=zstd:1: {btrfs_opts}"
    assert "noatime" in btrfs_opts, f"btrfs options missing noatime: {btrfs_opts}"
    for extra_key in ("ssdOptions", "hddOptions"):
        if extra_key in btrfs_entry:
            extra_opts = btrfs_entry[extra_key]
            assert isinstance(extra_opts, list), f"Invalid btrfs {extra_key}: {extra_opts}"
            assert "compress=zstd:1" in extra_opts, f"btrfs {extra_key} missing compress=zstd:1: {extra_opts}"
            assert "noatime" in extra_opts, f"btrfs {extra_key} missing noatime: {extra_opts}"


def test_f22_bootloader_and_shellprocess_haswell_integration(repo_root: Path) -> None:
    mods = require_artifact(repo_root / "installer" / "calamares" / "modules", "calamares/modules")
    bl_text = require_artifact(mods / "bootloader.conf", "bootloader.conf").read_text(
        encoding="utf-8"
    )
    sp_text = require_artifact(mods / "shellprocess.conf", "shellprocess.conf").read_text(
        encoding="utf-8"
    )
    combined = bl_text + "\n" + sp_text
    assert "i915.enable_fbc=1" in combined
    assert "i915.fastboot=1" in combined
    assert "kite-hw-tune" in combined or "kite-bridge" in combined


# ===========================================================================
# Feature 23: Folio 9480m Hardware Validation Suite (6 tests)
# ===========================================================================


def test_f23_checklist_exists_and_covers_all_9480m_hardware(repo_root: Path) -> None:
    cl = require_artifact(
        repo_root / "installer" / "validation" / "folio9480m-checklist.md",
        "folio9480m-checklist.md",
    )
    text = cl.read_text(encoding="utf-8")
    for tok in (
        "i5-4210U",
        "i5-4310U",
        "i7-4600U",
        "crocus",
        "anv",
        "i965",
        "zram",
        "7260",
        "I218-LM",
        "Synaptics",
        "92HD91BXX",
        "VFS495",
        "Windows 11",
    ):
        assert tok in text, f"folio9480m-checklist.md missing {tok}"


def test_f23_validate_hardware_sh_bash_syntax(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    run_sh_syntax_check(git_bash_exe, sh)


def test_f23_validate_hardware_sh_help_exits_cleanly(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    res = subprocess.run(
        [git_bash_exe, str(sh), "--help"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0, f"validate-hardware.sh --help failed: {res.stderr}"


def test_f23_validate_hardware_checks_gpu_vulkan_vaapi(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    text = sh.read_text(encoding="utf-8")
    for tok in ("crocus", "i965", "vulkan", "va"):
        assert tok in text.lower(), f"validate-hardware.sh missing GPU/VA/Vulkan check: {tok}"


def test_f23_validate_hardware_checks_kernel_ntsync_binder_btrfs_zram(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    text = sh.read_text(encoding="utf-8")
    for tok in ("ntsync", "binder", "btrfs", "zstd:1", "@kitebridge", "zram"):
        assert tok in text, f"validate-hardware.sh missing kernel/storage check: {tok}"


def test_f23_validate_hardware_checks_9480m_peripherals(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    text = sh.read_text(encoding="utf-8")
    for tok in ("iwlwifi", "e1000e", "snd_hda_intel"):
        assert tok in text, f"validate-hardware.sh missing peripheral check: {tok}"
    assert "synaptics" in text.lower() or "libinput" in text.lower()
    assert "vfs495" in text.lower() or "138a" in text.lower() or "fingerprint" in text.lower()
