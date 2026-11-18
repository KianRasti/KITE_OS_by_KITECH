"""Tier 1 Category-Partition E2E tests for Features 1–8 (Foundation, ISO, Scripts, CI)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.conftest import (
    AGENTS_BYTES,
    AGENTS_LINES,
    AGENTS_SHA256,
    ISO_FILENAME,
    SKILL_BYTES,
    SKILL_LINES,
    SKILL_SHA256,
    require_artifact,
    run_ps1_syntax_check,
    run_sh_syntax_check,
    run_yaml_load_check,
    scan_active_forbidden_assignments,
)

pytestmark = pytest.mark.tier1


def _build_minimal_valid_repo_fixture(tmp_path: Path) -> Path:
    """Create a minimal valid KITE_OS repo tree satisfying all 5 hardware invariants."""
    root = tmp_path / "valid_repo"
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d").mkdir(parents=True)
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "pacman.conf").write_text(
        "[options]\nArchitecture = x86_64 x86_64_v3\n[cachyos-v3]\nInclude = /etc/pacman.d/cachyos-v3-mirrorlist\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "packages.x86_64").write_text(
        "linux-cachyos\nmesa\nvulkan-intel\nlibva-intel-driver\npipewire\nbtrfs-progs\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "airootfs" / "etc" / "modules-load.d").mkdir(parents=True)
    (root / "iso-profile" / "airootfs" / "etc" / "modules-load.d" / "kite-os.conf").write_text(
        "ntsync\nbinder_linux\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "efiboot" / "loader" / "entries").mkdir(parents=True)
    (root / "iso-profile" / "efiboot" / "loader" / "entries" / "kite-os.conf").write_text(
        "title KITE_OS\noptions i915.enable_fbc=1 i915.fastboot=1 intel_pstate=active\n",
        encoding="utf-8",
    )
    (root / "kite-hw-tune" / "config").mkdir(parents=True)
    (root / "kite-hw-tune" / "config" / "kite-haswell.env").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n",
        encoding="utf-8",
    )
    (root / "kite-hw-tune" / "tuner.py").write_text(
        "# crocus i965 lz4 zstd rotational bfq kyber\n"
        "TIERS = ('lz4', 'zstd')\nSCHED = ('rotational', 'bfq', 'kyber')\n",
        encoding="utf-8",
    )
    (root / "kite-bridge" / "scripts").mkdir(parents=True)
    (root / "kite-bridge" / "scripts" / "provision-wine.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nDXVK_VER=1.10.3\n",
        encoding="utf-8",
    )
    (root / "kite-bridge" / "bridge.py").write_text(
        "CPU = 'Haswell-noTSX,+invtsc,vendor=GenuineIntel'\nPROP = 'persist.waydroid.multi_windows'\n",
        encoding="utf-8",
    )
    (root / "installer" / "calamares" / "modules").mkdir(parents=True)
    (root / "installer" / "calamares" / "modules" / "mount.conf").write_text(
        "btrfsSubvolumes:\n"
        "  - mountPoint: /\n    subvolume: /@\n"
        "  - mountPoint: /home\n    subvolume: /@home\n"
        "  - mountPoint: /var/lib/kitebridge\n    subvolume: /@kitebridge\n"
        "  - mountPoint: /.snapshots\n    subvolume: /@snapshots\n"
        "mountOptions:\n"
        "  - filesystem: btrfs\n    options: [compress=zstd:1, noatime]\n",
        encoding="utf-8",
    )
    (root / "installer" / "calamares" / "modules" / "bootloader.conf").write_text(
        "kernelParams:\n  - i915.enable_fbc=1\n  - i915.fastboot=1\n  - intel_pstate=active\n",
        encoding="utf-8",
    )
    return root


def _run_check_invariants(
    python_exe: str, script: Path, target_root: Path, extra: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    help_res = subprocess.run(
        [python_exe, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    help_txt = (help_res.stdout or "") + "\n" + (help_res.stderr or "")
    cmd = [python_exe, str(script)]
    if "--root" in help_txt:
        cmd.extend(["--root", str(target_root)])
    elif "--repo-root" in help_txt:
        cmd.extend(["--repo-root", str(target_root)])
    else:
        cmd.append(str(target_root))
    if extra:
        cmd.extend(extra)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


# ===========================================================================
# Feature 1: Verbatim AGENTS.md (6 tests)
# ===========================================================================


def test_f1_agents_exists_and_exact_sha256(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "Verbatim workspace rules")
    raw = agents.read_bytes()
    assert len(raw) == AGENTS_BYTES, f"AGENTS.md byte count {len(raw)} != {AGENTS_BYTES}"
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == AGENTS_SHA256, f"AGENTS.md SHA-256 mismatch: {digest} != {AGENTS_SHA256}"


def test_f1_agents_utf8_no_bom_lf_35_lines(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "Verbatim workspace rules")
    raw = agents.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "AGENTS.md must not have UTF-8 BOM"
    assert b"\r" not in raw, "AGENTS.md must use LF line endings only (no CR)"
    assert raw.endswith(b"\n"), "AGENTS.md must end with trailing LF"
    text = raw.decode("utf-8")
    assert len(text.splitlines()) == AGENTS_LINES


def test_f1_agents_no_yaml_frontmatter_and_header(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "Verbatim workspace rules")
    text = agents.read_text(encoding="utf-8")
    assert not text.lstrip().startswith("---"), "AGENTS.md must not contain YAML frontmatter"
    first_line = text.splitlines()[0]
    assert first_line == "# KITE_OS Workspace Rules (HP EliteBook Folio 9480m)"


def test_f1_agents_all_five_sections_present(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "Verbatim workspace rules")
    text = agents.read_text(encoding="utf-8")
    headings = [
        "## 1. Base System & CPU Target",
        "## 2. Intel HD Graphics 4400 (Haswell GT2) Constraints",
        "## 3. Dynamic Hardware Scaling (`kite-hw-tune`)",
        "## 4. Windows 11 Glass UI Shell (`kite-shell`)",
        "## 5. `KiteBridge` Universal App & File Runtime",
    ]
    positions = [text.find(h) for h in headings]
    for h, pos in zip(headings, positions):
        assert pos != -1, f"Missing heading in AGENTS.md: {h}"
    assert positions == sorted(positions), "AGENTS.md section headings are out of order"


def test_f1_agents_verbatim_line_diff_against_spec(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "Verbatim workspace rules")
    actual_lines = agents.read_text(encoding="utf-8").splitlines()
    spec_path = Path(
        r"C:\Users\Kian\.gemini\antigravity\brain\060d9773-3844-439b-9474-a86feecbc444\learning_proposal.md"
    )
    if spec_path.is_file():
        lp_lines = spec_path.read_text(encoding="utf-8").splitlines()
        expected_lines = lp_lines[27:62]
        assert actual_lines[:35] == expected_lines, "AGENTS.md L1-35 differs from learning_proposal.md L28-62"
    else:
        assert len(actual_lines) == AGENTS_LINES
        assert hashlib.sha256(agents.read_bytes()).hexdigest() == AGENTS_SHA256


def test_f1_agents_key_hardware_invariants_documented(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "Verbatim workspace rules")
    text = agents.read_text(encoding="utf-8")
    for token in (
        "x86-64-v3",
        "compress=zstd:1,noatime",
        "`@`",
        "`@home`",
        "`@kitebridge`",
        "`@snapshots`",
        "MESA_LOADER_DRIVER_OVERRIDE=crocus",
        "i965",
        "1.10.3",
        "size=6, passes=2, xray=true",
        "persist.waydroid.multi_windows=true",
        "-cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel",
    ):
        assert token in text, f"Missing hardware invariant token in AGENTS.md: {token}"


# ===========================================================================
# Feature 2: Verbatim .agents/skills/kite-os-builder/SKILL.md (6 tests)
# ===========================================================================


def test_f2_skill_exists_and_exact_sha256(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md",
        "Verbatim kite-os-builder skill",
    )
    raw = skill.read_bytes()
    assert len(raw) == SKILL_BYTES, f"SKILL.md byte count {len(raw)} != {SKILL_BYTES}"
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == SKILL_SHA256, f"SKILL.md SHA-256 mismatch: {digest} != {SKILL_SHA256}"


def test_f2_skill_utf8_no_bom_lf_37_lines(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md",
        "Verbatim kite-os-builder skill",
    )
    raw = skill.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "SKILL.md must not have UTF-8 BOM"
    assert b"\r" not in raw, "SKILL.md must use LF line endings only"
    assert raw.endswith(b"\n"), "SKILL.md must end with trailing LF"
    text = raw.decode("utf-8")
    assert len(text.splitlines()) == SKILL_LINES


def test_f2_skill_yaml_frontmatter_schema(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md",
        "Verbatim kite-os-builder skill",
    )
    lines = skill.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", "SKILL.md must start with YAML frontmatter delimiter"
    end_idx = lines.index("---", 1)
    fm = yaml.safe_load("\n".join(lines[1:end_idx]))
    assert isinstance(fm, dict)
    assert fm.get("name") == "kite-os-builder"
    desc = fm.get("description", "")
    assert isinstance(desc, str)
    for kw in (
        "HP EliteBook Folio 9480m",
        "archiso",
        "kite-hw-tune",
        "kite-shell",
        "KiteBridge",
        "WSL2",
        "Docker",
        "QEMU",
        "GitHub Actions",
    ):
        assert kw in desc, f"SKILL.md description missing keyword: {kw}"


def test_f2_skill_all_four_sections_present(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md",
        "Verbatim kite-os-builder skill",
    )
    text = skill.read_text(encoding="utf-8")
    for heading in (
        "# KITE_OS Builder & Verification Runbook",
        "## 1. Repository Layout",
        "## 2. Building the Bootable ISO from Windows",
        "## 3. Verifying in QEMU (Haswell Simulation)",
        "## 4. Verifying `KiteBridge` Runtimes",
    ):
        assert heading in text, f"Missing heading in SKILL.md: {heading}"


def test_f2_skill_repo_layout_entries_and_iso_target(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md",
        "Verbatim kite-os-builder skill",
    )
    text = skill.read_text(encoding="utf-8")
    for entry in (
        "iso-profile/",
        "kite-hw-tune/",
        "kite-shell/",
        "kite-bridge/",
        "installer/",
        "scripts/",
        f"out/{ISO_FILENAME}",
        ".github/workflows/build-iso.yml",
    ):
        assert entry in text, f"Missing repo/ISO target in SKILL.md: {entry}"


def test_f2_skill_verification_commands_present(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md",
        "Verbatim kite-os-builder skill",
    )
    text = skill.read_text(encoding="utf-8")
    for cmd_tok in (
        "-cpu Haswell-noTSX",
        "-m 4G",
        "-m 8G",
        "-m 16G",
        "systemctl status kite-hw-tune",
        "/dev/ntsync",
        "/dev/binder*",
        "crocus",
        "anv",
        "i965",
        "DXVK_VER=1.10.3",
        "persist.waydroid.multi_windows",
        "darling-dmg",
        "apfs-fuse",
        "/dev/kvm",
    ):
        assert cmd_tok in text, f"Missing verification command token in SKILL.md: {cmd_tok}"


# ===========================================================================
# Feature 3: Monorepo README.md (6 tests)
# ===========================================================================


def test_f3_readme_exists_utf8_non_trivial(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "Monorepo README.md")
    text = readme.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) >= 40, f"README.md too short ({len(lines)} lines)"
    h1_lines = [ln for ln in lines if ln.startswith("# ")]
    assert h1_lines, "README.md missing top-level H1 heading"
    assert "KITE_OS" in h1_lines[0] and "9480m" in text


def test_f3_readme_documents_monorepo_layout(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "Monorepo README.md")
    text = readme.read_text(encoding="utf-8")
    for path_tok in (
        "iso-profile",
        "kite-hw-tune",
        "kite-shell",
        "preview",
        "kite-bridge",
        "installer",
        "scripts",
        ".github/workflows",
    ):
        assert path_tok in text, f"README.md missing layout directory: {path_tok}"


def test_f3_readme_documents_hardware_invariants(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "Monorepo README.md")
    text = readme.read_text(encoding="utf-8")
    for inv in (
        "Haswell",
        "HD 4400",
        "x86-64-v3",
        "CachyOS",
        "crocus",
        "anv",
        "i965",
        "1.10.3",
        "zstd:1",
        "@home",
        "@kitebridge",
        "@snapshots",
    ):
        assert inv in text, f"README.md missing hardware invariant: {inv}"
    assert any(t in text for t in ("4 GB", "4GB", "4G"))
    assert any(t in text for t in ("8 GB", "8GB", "8G"))
    assert any(t in text for t in ("16 GB", "16GB", "16G"))


def test_f3_readme_documents_peripherals(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "Monorepo README.md")
    text = readme.read_text(encoding="utf-8")
    for periph in ("7260", "I218-LM", "Synaptics", "92HD91BXX", "VFS495"):
        assert periph in text, f"README.md missing Folio 9480m peripheral: {periph}"


def test_f3_readme_documents_build_and_qemu_workflows(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "Monorepo README.md")
    text = readme.read_text(encoding="utf-8")
    for wf in (
        "build-iso.ps1",
        "build-iso.sh",
        "test-qemu.ps1",
        "test-qemu.sh",
        "Haswell-noTSX",
        "build-iso.yml",
    ):
        assert wf in text, f"README.md missing build/QEMU workflow ref: {wf}"


def test_f3_readme_documents_preview_and_test_entrypoints(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "Monorepo README.md")
    text = readme.read_text(encoding="utf-8")
    assert "kite-shell/preview" in text
    assert "pytest" in text
    assert "check_invariants.py" in text


# ===========================================================================
# Feature 4: archiso Profile (iso-profile/) (6 tests)
# ===========================================================================


def test_f4_profiledef_and_bash_syntax(repo_root: Path, git_bash_exe: str) -> None:
    iso_dir = require_artifact(repo_root / "iso-profile", "archiso profile directory")
    profiledef = require_artifact(iso_dir / "profiledef.sh", "profiledef.sh")
    customize = require_artifact(
        iso_dir / "airootfs" / "root" / "customize_airootfs.sh", "customize_airootfs.sh"
    )
    mkinit = require_artifact(
        iso_dir / "airootfs" / "etc" / "mkinitcpio.conf", "mkinitcpio.conf"
    )
    for sh_file in (profiledef, customize, mkinit):
        run_sh_syntax_check(git_bash_exe, sh_file)

    pd_text = profiledef.read_text(encoding="utf-8")
    assert "kite-os-folio9480" in pd_text
    assert 'arch="x86_64"' in pd_text or "arch='x86_64'" in pd_text or "x86_64" in pd_text
    assert "zstd" in pd_text


def test_f4_pacman_conf_cachyos_v3_repos(repo_root: Path) -> None:
    pacman_conf = require_artifact(repo_root / "iso-profile" / "pacman.conf", "pacman.conf")
    text = pacman_conf.read_text(encoding="utf-8")
    assert re.search(r"cachyos.*v3", text, re.IGNORECASE), "Missing CachyOS x86-64-v3 repo"
    assert "x86_64_v3" in text or "x86-64-v3" in text, "Missing x86_64_v3 Architecture setting"


def test_f4_packages_x86_64_required_and_forbidden(repo_root: Path) -> None:
    pkg_file = require_artifact(repo_root / "iso-profile" / "packages.x86_64", "packages.x86_64")
    active_pkgs = [
        ln.split("#", 1)[0].strip()
        for ln in pkg_file.read_text(encoding="utf-8").splitlines()
    ]
    active_pkgs = [p for p in active_pkgs if p]
    pkg_set = set(active_pkgs)

    forbidden_pkg = "intel-media-" + "driver"
    assert forbidden_pkg not in pkg_set, f"Forbidden package active in packages.x86_64: {forbidden_pkg}"

    for req in (
        "linux-cachyos",
        "mesa",
        "vulkan-intel",
        "libva-intel-driver",
        "pipewire",
        "btrfs-progs",
        "linux-firmware",
        "networkmanager",
        "bluez",
        "thermald",
    ):
        assert any(p == req or p.startswith(req + "-") for p in pkg_set), (
            f"Required package '{req}' missing from packages.x86_64"
        )


def test_f4_haswell_gpu_env_pins_crocus_and_i965(repo_root: Path) -> None:
    etc_dir = require_artifact(repo_root / "iso-profile" / "airootfs" / "etc", "airootfs/etc")
    env_conf = require_artifact(
        etc_dir / "environment.d" / "10-kite-haswell.conf", "10-kite-haswell.conf"
    )
    combined = env_conf.read_text(encoding="utf-8")
    etc_env = etc_dir / "environment"
    if etc_env.is_file():
        combined += "\n" + etc_env.read_text(encoding="utf-8")

    mesa_vals: list[str] = []
    va_vals: list[str] = []
    assign_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
    for raw_line in combined.splitlines():
        clean = raw_line.split("#", 1)[0].strip()
        if not clean:
            continue
        m = assign_re.match(clean)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().strip("\"'")
        if key == "MESA_LOADER_DRIVER_OVERRIDE":
            mesa_vals.append(val)
        elif key == "LIBVA_DRIVER_NAME":
            va_vals.append(val)

    assert set(mesa_vals) == {"crocus"}, (
        f"Expected active MESA_LOADER_DRIVER_OVERRIDE=crocus only, got {mesa_vals}"
    )
    assert set(va_vals) == {"i965"}, (
        f"Expected active LIBVA_DRIVER_NAME=i965 only, got {va_vals}"
    )


def test_f4_kernel_modules_and_modprobe_haswell(repo_root: Path) -> None:
    etc_dir = require_artifact(repo_root / "iso-profile" / "airootfs" / "etc", "airootfs/etc")
    mod_load_dir = require_artifact(etc_dir / "modules-load.d", "modules-load.d")
    modprobe_dir = require_artifact(etc_dir / "modprobe.d", "modprobe.d")

    mod_load_text = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(mod_load_dir.glob("*.conf"))
    )
    assert "ntsync" in mod_load_text, "ntsync missing in modules-load.d"
    assert "binder_linux" in mod_load_text, "binder_linux missing in modules-load.d"

    modprobe_text = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(modprobe_dir.glob("*.conf"))
    )
    assert "enable_fbc=1" in modprobe_text and "fastboot=1" in modprobe_text


def test_f4_bootloaders_efiboot_grub_syslinux_kernel_params(repo_root: Path) -> None:
    iso_dir = require_artifact(repo_root / "iso-profile", "iso-profile")
    efi_entries = sorted((iso_dir / "efiboot" / "loader" / "entries").glob("*.conf"))
    grub_cfg = require_artifact(iso_dir / "grub" / "grub.cfg", "grub.cfg")
    syslinux_cfgs = sorted((iso_dir / "syslinux").glob("*.cfg"))

    assert efi_entries, "No efiboot loader entries found"
    assert syslinux_cfgs, "No syslinux cfg files found"

    efi_text = "\n".join(p.read_text(encoding="utf-8") for p in efi_entries)
    grub_text = grub_cfg.read_text(encoding="utf-8")
    syslinux_text = "\n".join(p.read_text(encoding="utf-8") for p in syslinux_cfgs)

    for label, txt in (("efiboot", efi_text), ("grub", grub_text), ("syslinux", syslinux_text)):
        assert "linux-cachyos" in txt, f"{label} missing linux-cachyos kernel reference"
        assert "i915.enable_fbc=1" in txt, f"{label} missing i915.enable_fbc=1"
        assert "i915.fastboot=1" in txt, f"{label} missing i915.fastboot=1"


# ===========================================================================
# Feature 5: ISO Build Scripts (build-iso.sh, build-iso.ps1) (6 tests)
# ===========================================================================


def test_f5_build_iso_sh_bash_syntax_and_safety(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "build-iso.sh", "build-iso.sh")
    run_sh_syntax_check(git_bash_exe, sh_path)
    text = sh_path.read_text(encoding="utf-8")
    assert "set -e" in text or "set -euo pipefail" in text


def test_f5_build_iso_ps1_powershell51_parser(
    repo_root: Path, powershell_exe: str
) -> None:
    ps1_path = require_artifact(repo_root / "scripts" / "build-iso.ps1", "build-iso.ps1")
    run_ps1_syntax_check(powershell_exe, ps1_path)


def test_f5_build_iso_sh_targets_profile_privileged_and_iso_output(repo_root: Path) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "build-iso.sh", "build-iso.sh")
    text = sh_path.read_text(encoding="utf-8")
    assert "iso-profile" in text
    assert "mkarchiso" in text
    assert "--privileged" in text
    assert ISO_FILENAME in text
    assert "sha256" in text.lower()


def test_f5_build_iso_ps1_bridges_wsl_or_docker_and_iso_output(repo_root: Path) -> None:
    ps1_path = require_artifact(repo_root / "scripts" / "build-iso.ps1", "build-iso.ps1")
    text = ps1_path.read_text(encoding="utf-8")
    assert ("wsl" in text.lower() or "docker" in text.lower())
    assert "--privileged" in text
    assert "build-iso.sh" in text or "mkarchiso" in text
    assert ISO_FILENAME in text


def test_f5_build_iso_sh_help_and_dry_run(repo_root: Path, git_bash_exe: str) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "build-iso.sh", "build-iso.sh")
    res_help = subprocess.run(
        [git_bash_exe, str(sh_path), "--help"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res_help.returncode == 0, f"build-iso.sh --help failed: {res_help.stderr}"

    res_dry = subprocess.run(
        [git_bash_exe, str(sh_path), "--dry-run"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res_dry.returncode == 0, f"build-iso.sh --dry-run failed: {res_dry.stderr}"
    combined = res_dry.stdout + res_dry.stderr
    assert "mkarchiso" in combined or ISO_FILENAME in combined


def test_f5_build_iso_ps1_help_or_dry_run(repo_root: Path, powershell_exe: str) -> None:
    ps1_path = require_artifact(repo_root / "scripts" / "build-iso.ps1", "build-iso.ps1")
    res = subprocess.run(
        [
            powershell_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1_path),
            "-DryRun",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"build-iso.ps1 -DryRun failed: {res.stderr}\n{res.stdout}"
    combined = res.stdout + res.stderr
    assert ISO_FILENAME in combined or "mkarchiso" in combined or "build-iso.sh" in combined


# ===========================================================================
# Feature 6: QEMU Haswell Runners (test-qemu.sh, test-qemu.ps1) (6 tests)
# ===========================================================================


def test_f6_test_qemu_sh_bash_syntax(repo_root: Path, git_bash_exe: str) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    run_sh_syntax_check(git_bash_exe, sh_path)


def test_f6_test_qemu_ps1_powershell51_parser(repo_root: Path, powershell_exe: str) -> None:
    ps1_path = require_artifact(repo_root / "scripts" / "test-qemu.ps1", "test-qemu.ps1")
    run_ps1_syntax_check(powershell_exe, ps1_path)


def test_f6_test_qemu_sh_dry_run_ram_tiers_4g_8g_16g(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    for tier in ("4G", "8G", "16G"):
        res = subprocess.run(
            [git_bash_exe, str(sh_path), "--dry-run", "--ram", tier],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, f"test-qemu.sh --dry-run --ram {tier} failed: {res.stderr}"
        out = res.stdout + res.stderr
        assert "qemu-system-x86_64" in out
        assert "-cpu Haswell-noTSX" in out
        assert "-smp 4,cores=2,threads=2" in out
        assert f"-m {tier}" in out


def test_f6_test_qemu_sh_dry_run_ovmf_e1000e_and_rotational_disk(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    help_txt = subprocess.run(
        [git_bash_exe, str(sh_path), "--help"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout
    outputs: dict[str, str] = {}
    if "--rotational" in help_txt:
        variants = [("ssd", ["--rotational", "0"]), ("hdd", ["--rotational", "1"])]
    else:
        variants = [("ssd", ["--disk", "ssd"]), ("hdd", ["--disk", "hdd"])]
    for disk_mode, disk_args in variants:
        res = subprocess.run(
            [git_bash_exe, str(sh_path), "--dry-run", "--ram", "8G", *disk_args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, f"test-qemu.sh {disk_args} failed: {res.stderr}"
        out = res.stdout + res.stderr
        assert "OVMF" in out or "ovmf" in out.lower()
        assert "e1000e" in out
        assert ISO_FILENAME in out
        outputs[disk_mode] = out
    assert outputs["ssd"] != outputs["hdd"], "SSD and HDD dry-run commands must differ in rotational config"


def test_f6_test_qemu_ps1_dry_run_haswell_and_tiers(
    repo_root: Path, powershell_exe: str
) -> None:
    ps1_path = require_artifact(repo_root / "scripts" / "test-qemu.ps1", "test-qemu.ps1")
    for tier in ("4G", "8G", "16G"):
        res = subprocess.run(
            [
                powershell_exe,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1_path),
                "-DryRun",
                "-Ram",
                tier,
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert res.returncode == 0, f"test-qemu.ps1 -DryRun -Ram {tier} failed: {res.stderr}"
        out = res.stdout + res.stderr
        assert "-cpu Haswell-noTSX" in out
        assert "-smp 4,cores=2,threads=2" in out
        assert f"-m {tier}" in out
        assert "e1000e" in out
        assert "OVMF" in out or "ovmf" in out.lower()


def test_f6_test_qemu_help_documented_options(
    repo_root: Path, git_bash_exe: str, powershell_exe: str
) -> None:
    sh_path = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    ps1_path = require_artifact(repo_root / "scripts" / "test-qemu.ps1", "test-qemu.ps1")

    res_sh = subprocess.run(
        [git_bash_exe, str(sh_path), "--help"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res_sh.returncode == 0
    for kw in ("4G", "8G", "16G", "ssd", "hdd"):
        assert kw.lower() in res_sh.stdout.lower(), f"test-qemu.sh --help missing {kw}"

    ps1_text = ps1_path.read_text(encoding="utf-8")
    if re.search(r"\[\s*switch\s*\]\s*\$Help\b", ps1_text, re.IGNORECASE):
        res_ps = subprocess.run(
            [
                powershell_exe,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1_path),
                "-Help",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    else:
        escaped_ps1 = str(ps1_path.resolve()).replace("'", "''")
        res_ps = subprocess.run(
            [
                powershell_exe,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Get-Help '{escaped_ps1}' -Full | Out-String",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert res_ps.returncode == 0, f"PowerShell help failed: {res_ps.stderr}"
    ps_out = (res_ps.stdout + res_ps.stderr).lower()
    for kw in ("4g", "8g", "16g"):
        assert kw in ps_out, f"test-qemu.ps1 help missing {kw}"
    assert "rotational" in ps_out or ("ssd" in ps_out and "hdd" in ps_out)


# ===========================================================================
# Feature 7: GitHub Actions CI (.github/workflows/build-iso.yml) (6 tests)
# ===========================================================================


def test_f7_workflow_valid_yaml_and_top_level_schema(repo_root: Path) -> None:
    wf = require_artifact(
        repo_root / ".github" / "workflows" / "build-iso.yml", "GitHub Actions CI workflow"
    )
    data = run_yaml_load_check(wf)
    assert isinstance(data, dict)
    assert "name" in data
    assert "on" in data or True in data
    assert isinstance(data.get("jobs"), dict) and len(data["jobs"]) >= 1


def test_f7_workflow_triggers_push_pr_dispatch(repo_root: Path) -> None:
    wf = require_artifact(
        repo_root / ".github" / "workflows" / "build-iso.yml", "GitHub Actions CI workflow"
    )
    data = run_yaml_load_check(wf)
    triggers = data.get("on") if "on" in data else data.get(True)
    assert isinstance(triggers, dict), "Workflow triggers must be a mapping"
    for trig in ("push", "pull_request", "workflow_dispatch"):
        assert trig in triggers, f"Missing CI trigger: {trig}"


def test_f7_workflow_has_validate_job(repo_root: Path) -> None:
    wf = require_artifact(
        repo_root / ".github" / "workflows" / "build-iso.yml", "GitHub Actions CI workflow"
    )
    text = wf.read_text(encoding="utf-8")
    assert "check_invariants.py" in text
    assert "pytest" in text


def test_f7_workflow_has_privileged_archiso_build_job(repo_root: Path) -> None:
    wf = require_artifact(
        repo_root / ".github" / "workflows" / "build-iso.yml", "GitHub Actions CI workflow"
    )
    data = run_yaml_load_check(wf)
    text = wf.read_text(encoding="utf-8")
    assert "ubuntu-latest" in text
    assert "--privileged" in text
    assert "mkarchiso" in text or "build-iso.sh" in text
    assert "iso-profile" in text or "build-iso.sh" in text
    assert any("arch" in str(j).lower() or "cachyos" in str(j).lower() for j in data["jobs"].values())


def test_f7_workflow_generates_iso_and_sha256_artifacts(repo_root: Path) -> None:
    wf = require_artifact(
        repo_root / ".github" / "workflows" / "build-iso.yml", "GitHub Actions CI workflow"
    )
    text = wf.read_text(encoding="utf-8")
    assert ISO_FILENAME in text
    assert "sha256" in text.lower()
    assert "actions/upload-artifact" in text


def test_f7_workflow_build_depends_on_validate_or_runs_invariants(repo_root: Path) -> None:
    wf = require_artifact(
        repo_root / ".github" / "workflows" / "build-iso.yml", "GitHub Actions CI workflow"
    )
    data = run_yaml_load_check(wf)
    jobs: dict[str, Any] = data["jobs"]
    build_jobs = [j for name, j in jobs.items() if "build" in name.lower()]
    assert build_jobs, "No build job found in build-iso.yml"
    has_needs = any(bool(j.get("needs")) for j in build_jobs)
    assert has_needs or "check_invariants.py" in str(build_jobs[0])
    text = wf.read_text(encoding="utf-8")
    assert re.search(r"actions/checkout@v\d+", text)
    assert re.search(r"actions/upload-artifact@v\d+", text)


# ===========================================================================
# Feature 8: Repo Invariant Checker (scripts/check_invariants.py) (6 tests)
# ===========================================================================


def test_f8_check_invariants_valid_python_and_help(
    repo_root: Path, python_exe: str
) -> None:
    script = require_artifact(
        repo_root / "scripts" / "check_invariants.py", "check_invariants.py"
    )
    res = subprocess.run(
        [python_exe, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0, f"check_invariants.py --help failed: {res.stderr}"
    assert "usage" in (res.stdout + res.stderr).lower()


def test_f8_check_invariants_passes_on_live_repo(
    repo_root: Path, python_exe: str
) -> None:
    script = require_artifact(
        repo_root / "scripts" / "check_invariants.py", "check_invariants.py"
    )
    res = _run_check_invariants(python_exe, script, repo_root)
    assert res.returncode == 0, (
        f"check_invariants.py failed on live repo:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def test_f8_check_invariants_reports_all_five_invariant_checks(
    repo_root: Path, python_exe: str
) -> None:
    script = require_artifact(
        repo_root / "scripts" / "check_invariants.py", "check_invariants.py"
    )
    help_txt = subprocess.run(
        [python_exe, str(script), "--help"], capture_output=True, text=True, timeout=20
    ).stdout
    extra = ["--json"] if "--json" in help_txt else []
    res = _run_check_invariants(python_exe, script, repo_root, extra=extra)
    assert res.returncode == 0
    if extra == ["--json"]:
        payload = json.loads(res.stdout)
        assert payload.get("ok") is True
        assert payload.get("violations") == []
        passed = " ".join(payload.get("checks_passed", [])).lower()
        for tok in ("iso-profile:env-pins", "iso-profile:packages", "kite-hw-tune", "kite-bridge", "installer"):
            assert tok in passed, f"check_invariants.py --json missing check '{tok}'"
    else:
        combined = (res.stdout + res.stderr).lower()
        assert "pass" in combined


def test_f8_check_invariants_accepts_custom_root_fixture(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(
        repo_root / "scripts" / "check_invariants.py", "check_invariants.py"
    )
    valid_root = _build_minimal_valid_repo_fixture(tmp_path)
    res = _run_check_invariants(python_exe, script, valid_root)
    assert res.returncode == 0, (
        f"check_invariants.py failed on valid minimal fixture:\n{res.stdout}\n{res.stderr}"
    )


def test_f8_check_invariants_ignores_negative_mentions_in_docs_and_tests(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(
        repo_root / "scripts" / "check_invariants.py", "check_invariants.py"
    )
    valid_root = _build_minimal_valid_repo_fixture(tmp_path)
    bad_drv = "intel-media-" + "driver"
    bad_gl = "ir" + "is"
    bad_va = "iH" + "D"
    bad_dxvk = "DXVK " + "2.0+"
    (valid_root / "README.md").write_text(
        f"Avoid {bad_gl} and {bad_drv} ({bad_va}); reject {bad_dxvk}.\n",
        encoding="utf-8",
    )
    (valid_root / "docs").mkdir(exist_ok=True)
    (valid_root / "docs" / "notes.md").write_text(
        f"Do NOT configure {bad_gl}. Never use {bad_drv} or {bad_dxvk}.\n",
        encoding="utf-8",
    )
    (valid_root / "tests").mkdir(exist_ok=True)
    (valid_root / "tests" / "test_neg.py").write_text(
        f"assert '{bad_gl}' not in active_cfg\n", encoding="utf-8"
    )
    res = _run_check_invariants(python_exe, script, valid_root)
    assert res.returncode == 0, (
        f"check_invariants.py false-positived on docs/tests:\n{res.stdout}\n{res.stderr}"
    )


def test_f8_check_invariants_no_forbidden_active_drivers_independent_scan(
    repo_root: Path,
) -> None:
    present_dirs = [
        d
        for d in ("iso-profile", "kite-hw-tune", "kite-shell", "kite-bridge", "installer")
        if (repo_root / d).exists()
    ]
    if not present_dirs:
        require_artifact(repo_root / "iso-profile", "OS/bridge directories")
    violations = scan_active_forbidden_assignments(repo_root, present_dirs)
    assert not violations, "Forbidden active driver assignments found:\n" + "\n".join(violations)
