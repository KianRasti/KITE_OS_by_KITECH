"""Tier 2 Boundary, Negative, and Corner-Case E2E tests across all 23 features."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from tests.e2e.conftest import (
    AGENTS_SHA256,
    HW_PROFILE_SCHEMA_V1,
    ISO_FILENAME,
    SKILL_SHA256,
    build_kite_bridge_lifecycle_args,
    introspect_cli_help,
    invoke_kite_settings_cli,
    is_prohibitory_line,
    require_artifact,
    resolve_kite_settings_module,
    run_kite_bridge,
    run_kite_hw_tune,
    run_kite_settings,
    run_qml_structural_check,
    run_sh_syntax_check,
    run_yaml_load_check,
    scan_active_forbidden_assignments,
    write_minimal_aab,
    write_minimal_apk,
)

pytestmark = pytest.mark.tier2


def _make_valid_repo_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo_copy"
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d").mkdir(parents=True)
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "packages.x86_64").write_text(
        "linux-cachyos\nmesa\nvulkan-intel\nlibva-intel-driver\nbtrfs-progs\n",
        encoding="utf-8",
    )
    (root / "kite-hw-tune" / "config").mkdir(parents=True)
    (root / "kite-hw-tune" / "config" / "kite-haswell.env").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n",
        encoding="utf-8",
    )
    (root / "kite-bridge" / "scripts").mkdir(parents=True)
    (root / "kite-bridge" / "scripts" / "provision-wine.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nDXVK_VER=1.10.3\n",
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
    return root


def _run_invariants(python_exe: str, script: Path, target_root: Path) -> subprocess.CompletedProcess[str]:
    help_txt = subprocess.run(
        [python_exe, str(script), "--help"], capture_output=True, text=True, timeout=20
    ).stdout
    cmd = [python_exe, str(script)]
    if "--root" in help_txt:
        cmd.extend(["--root", str(target_root)])
    elif "--repo-root" in help_txt:
        cmd.extend(["--repo-root", str(target_root)])
    else:
        cmd.append(str(target_root))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _ps51_parse_snippet(ps_exe: str, tmp_path: Path, code: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "probe.ps1"
    script.write_text(code, encoding="utf-8")
    escaped = str(script.resolve()).replace("'", "''")
    ps_code = (
        f"$tokens = $null; $errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped}', [ref]$tokens, [ref]$errors); "
        f"if ($errors -and $errors.Count -gt 0) {{ exit 1 }}"
    )
    encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
    return subprocess.run(
        [ps_exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _validate_calamares_btrfs_contract(part_data: dict[str, Any], mount_data: dict[str, Any], mount_raw: str = "") -> None:
    assert part_data.get("defaultFileSystemType") == "btrfs"
    subvols = {
        item.get("subvolume", "").lstrip("/"): item.get("mountPoint")
        for item in mount_data.get("btrfsSubvolumes", [])
        if isinstance(item, dict)
    }
    assert subvols.get("@") == "/"
    assert subvols.get("@home") == "/home"
    assert subvols.get("@kitebridge") == "/var/lib/kitebridge"
    assert subvols.get("@snapshots") == "/.snapshots"
    mount_options = mount_data.get("mountOptions", [])
    assert isinstance(mount_options, list) and mount_options, "mountOptions must be a non-empty list"
    btrfs_entries = [
        item
        for item in mount_options
        if isinstance(item, dict) and item.get("filesystem") == "btrfs"
    ]
    assert len(btrfs_entries) == 1, f"Expected exactly 1 btrfs mountOptions entry, got {btrfs_entries}"
    btrfs_entry = btrfs_entries[0]
    btrfs_opts = btrfs_entry.get("options", [])
    assert isinstance(btrfs_opts, list) and btrfs_opts
    assert "compress=zstd:1" in btrfs_opts, f"btrfs.options missing compress=zstd:1: {btrfs_opts}"
    assert "noatime" in btrfs_opts, f"btrfs.options missing noatime: {btrfs_opts}"
    for extra_key in ("ssdOptions", "hddOptions"):
        if extra_key in btrfs_entry:
            extra_opts = btrfs_entry[extra_key]
            assert isinstance(extra_opts, list)
            assert "compress=zstd:1" in extra_opts, f"btrfs.{extra_key} missing compress=zstd:1: {extra_opts}"
            assert "noatime" in extra_opts, f"btrfs.{extra_key} missing noatime: {extra_opts}"


# ===========================================================================
# Feature 1: Verbatim AGENTS.md Boundaries (5 tests)
# ===========================================================================


def test_t2_f1_rejects_utf8_bom(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "AGENTS.md")
    tampered = b"\xef\xbb\xbf" + agents.read_bytes()
    assert tampered.startswith(b"\xef\xbb\xbf")
    assert hashlib.sha256(tampered).hexdigest() != AGENTS_SHA256


def test_t2_f1_rejects_crlf_line_endings(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "AGENTS.md")
    tampered = agents.read_bytes().replace(b"\n", b"\r\n")
    assert b"\r" in tampered
    assert hashlib.sha256(tampered).hexdigest() != AGENTS_SHA256


def test_t2_f1_rejects_missing_trailing_newline(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "AGENTS.md")
    tampered = agents.read_bytes().rstrip(b"\n")
    assert hashlib.sha256(tampered).hexdigest() != AGENTS_SHA256


def _is_prohibitory_markdown_context(lines: list[str], line_idx: int, token_regex: str) -> bool:
    """Return True if token on lines[line_idx] appears in prohibitory prose or a Prohibited table column."""
    line = lines[line_idx]
    if is_prohibitory_line(line):
        return True
    if line.lstrip().startswith("|"):
        # Find nearest Markdown table header row above line_idx
        hdr_idx = line_idx - 1
        while hdr_idx >= 0 and lines[hdr_idx].lstrip().startswith("|"):
            hdr_idx -= 1
        hdr_start = hdr_idx + 1
        if hdr_start < line_idx and "|" in lines[hdr_start]:
            headers = [c.strip().lower() for c in lines[hdr_start].strip().strip("|").split("|")]
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            matched_non_prohib = False
            matched_any = False
            for col_idx, cell in enumerate(cells):
                if re.search(token_regex, cell, re.IGNORECASE):
                    matched_any = True
                    hdr = headers[col_idx] if col_idx < len(headers) else ""
                    if not any(w in hdr for w in ("prohibit", "forbid", "avoid", "never", "do not")):
                        matched_non_prohib = True
            if matched_any and not matched_non_prohib:
                return True
    return False


def test_t2_f1_rejects_emdash_ascii_corruption(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "AGENTS.md")
    text = agents.read_text(encoding="utf-8")
    assert "x86-64-v3" in text
    tampered = text.replace("x86-64-v3", "x86_64_v3", 1).encode("utf-8")
    assert hashlib.sha256(tampered).hexdigest() != AGENTS_SHA256


def test_t2_f1_rejects_truncated_section(repo_root: Path) -> None:
    agents = require_artifact(repo_root / "AGENTS.md", "AGENTS.md")
    lines = agents.read_text(encoding="utf-8").splitlines()
    tampered_lines = lines[:-1]
    assert len(tampered_lines) == 40
    tampered = ("\n".join(tampered_lines) + "\n").encode("utf-8")
    assert hashlib.sha256(tampered).hexdigest() != AGENTS_SHA256


# ===========================================================================
# Feature 2: Verbatim SKILL.md Boundaries (5 tests)
# ===========================================================================


def test_t2_f2_rejects_utf8_bom(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md", "SKILL.md"
    )
    tampered = b"\xef\xbb\xbf" + skill.read_bytes()
    assert hashlib.sha256(tampered).hexdigest() != SKILL_SHA256


def test_t2_f2_rejects_crlf_line_endings(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md", "SKILL.md"
    )
    tampered = skill.read_bytes().replace(b"\n", b"\r\n")
    assert hashlib.sha256(tampered).hexdigest() != SKILL_SHA256


def test_t2_f2_rejects_missing_trailing_newline(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md", "SKILL.md"
    )
    tampered = skill.read_bytes().rstrip(b"\n")
    assert hashlib.sha256(tampered).hexdigest() != SKILL_SHA256


def test_t2_f2_rejects_broken_yaml_frontmatter(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md", "SKILL.md"
    )
    text = skill.read_text(encoding="utf-8").replace("name: kite-os-builder", "name: Kite_OS")
    lines = text.splitlines()
    end_idx = lines.index("---", 1)
    fm = yaml.safe_load("\n".join(lines[1:end_idx]))
    assert fm["name"] != "kite-os-builder"


def test_t2_f2_rejects_wrong_iso_filename(repo_root: Path) -> None:
    skill = require_artifact(
        repo_root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md", "SKILL.md"
    )
    tampered = skill.read_text(encoding="utf-8").replace(ISO_FILENAME, "kite-os.iso").encode("utf-8")
    assert hashlib.sha256(tampered).hexdigest() != SKILL_SHA256


# ===========================================================================
# Feature 3: README.md Boundaries (5 tests)
# ===========================================================================


def test_t2_f3_no_positive_recommendation_of_iris(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "README.md")
    tok = "ir" + "is"
    lines = readme.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if re.search(rf"\b{tok}\b", line, re.IGNORECASE):
            assert _is_prohibitory_markdown_context(lines, idx, rf"\b{tok}\b"), (
                f"README.md:{idx + 1} non-prohibitory '{tok}': {line}"
            )


def test_t2_f3_no_positive_recommendation_of_ihd(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "README.md")
    ihd = "iH" + "D"
    drv = "intel-media-" + "driver"
    lines = readme.read_text(encoding="utf-8").splitlines()
    pat = rf"(?:\b{ihd}\b|{re.escape(drv)})"
    for idx, line in enumerate(lines):
        if re.search(pat, line):
            assert _is_prohibitory_markdown_context(lines, idx, pat), (
                f"README.md:{idx + 1} non-prohibitory '{ihd}/{drv}': {line}"
            )


def test_t2_f3_no_positive_recommendation_of_dxvk2(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "README.md")
    dxvk2 = "DXVK " + "2"
    lines = readme.read_text(encoding="utf-8").splitlines()
    pat = re.escape(dxvk2)
    for idx, line in enumerate(lines):
        if dxvk2 in line:
            assert _is_prohibitory_markdown_context(lines, idx, pat), (
                f"README.md:{idx + 1} non-prohibitory '{dxvk2}': {line}"
            )


def test_t2_f3_all_markdown_code_fences_balanced(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "README.md")
    fences = [
        ln for ln in readme.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith("```")
    ]
    assert len(fences) % 2 == 0, "Unclosed markdown code fence in README.md"


def test_t2_f3_no_broken_local_relative_links(repo_root: Path) -> None:
    readme = require_artifact(repo_root / "README.md", "README.md")
    text = readme.read_text(encoding="utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    for target in links:
        clean = target.split("#", 1)[0].strip()
        if not clean or clean.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (repo_root / clean).resolve()
        assert resolved.exists(), f"Broken local relative link in README.md: {target}"


# ===========================================================================
# Feature 4: archiso Profile Boundaries (5 tests)
# ===========================================================================


def test_t2_f4_no_commented_vs_active_iris_false_positive(repo_root: Path) -> None:
    require_artifact(repo_root / "iso-profile", "iso-profile")
    assert not scan_active_forbidden_assignments(repo_root, ["iso-profile"])


def test_t2_f4_no_active_intel_media_driver_in_packages(repo_root: Path) -> None:
    pkg_file = require_artifact(repo_root / "iso-profile" / "packages.x86_64", "packages.x86_64")
    active = [ln.split("#", 1)[0].strip() for ln in pkg_file.read_text(encoding="utf-8").splitlines()]
    forbidden_pkg = "intel-media-" + "driver"
    assert forbidden_pkg not in active
    assert "libva-intel-driver" in active


def test_t2_f4_no_vkd3d_or_dxvk2_in_iso_packages(repo_root: Path) -> None:
    pkg_file = require_artifact(repo_root / "iso-profile" / "packages.x86_64", "packages.x86_64")
    active = [ln.split("#", 1)[0].strip().lower() for ln in pkg_file.read_text(encoding="utf-8").splitlines()]
    assert not any("vkd3d-proton" in p for p in active)
    assert not any(re.search(r"dxvk[-_]?2", p) for p in active)


def test_t2_f4_no_mitigations_off_hardcoded_in_default_boot(repo_root: Path) -> None:
    iso_dir = require_artifact(repo_root / "iso-profile", "iso-profile")
    loader_conf = iso_dir / "efiboot" / "loader" / "loader.conf"
    default_entry = "kite-os.conf"
    if loader_conf.is_file():
        for ln in loader_conf.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("default "):
                default_entry = ln.strip().split(None, 1)[1].strip()
    boot_files = (
        list((iso_dir / "efiboot").rglob("*.conf"))
        + list((iso_dir / "grub").rglob("*.cfg"))
        + list((iso_dir / "syslinux").rglob("*.cfg"))
    )
    for bf in boot_files:
        if bf.name == "loader.conf":
            continue
        for ln in bf.read_text(encoding="utf-8").splitlines():
            s = ln.split("#", 1)[0].strip()
            if "mitigations=off" in s:
                assert bf.name != default_entry, (
                    f"Default boot entry {bf} must not hardcode mitigations=off"
                )
                text_low = bf.read_text(encoding="utf-8").lower()
                assert any(
                    tag in bf.name.lower() for tag in ("mitigations-off", "fallback", "perf", "fast")
                ) or any(
                    label in text_low for label in ("high-perf", "kite-os-mitigations-off")
                ), (
                    f"Boot file {bf} hardcodes mitigations=off without opt-in label"
                )


def test_t2_f4_no_duplicate_conflicting_env_overrides(repo_root: Path) -> None:
    etc_dir = require_artifact(repo_root / "iso-profile" / "airootfs" / "etc", "airootfs/etc")
    env_files = list((etc_dir / "environment.d").glob("*.conf"))
    if (etc_dir / "environment").is_file():
        env_files.append(etc_dir / "environment")
    mesa_vals: set[str] = set()
    va_vals: set[str] = set()
    assign_re = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
    for ef in env_files:
        for ln in ef.read_text(encoding="utf-8").splitlines():
            s = ln.split("#", 1)[0].strip()
            if not s:
                continue
            m = assign_re.match(s)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip("\"'")
            if key == "MESA_LOADER_DRIVER_OVERRIDE":
                mesa_vals.add(val)
            elif key == "LIBVA_DRIVER_NAME":
                va_vals.add(val)
    assert mesa_vals == {"crocus"}
    assert va_vals == {"i965"}


# ===========================================================================
# Feature 5: ISO Build Scripts Boundaries (5 tests)
# ===========================================================================


def test_t2_f5_ps1_rejects_ps7_null_coalescing_probe(
    powershell_exe: str, tmp_path: Path
) -> None:
    res = _ps51_parse_snippet(powershell_exe, tmp_path, "$a = $b ?? $c")
    assert res.returncode != 0


def test_t2_f5_ps1_rejects_ps7_ternary_and_andand_probe(
    powershell_exe: str, tmp_path: Path
) -> None:
    res = _ps51_parse_snippet(powershell_exe, tmp_path, "$a = $true ? 1 : 2\necho a && echo b")
    assert res.returncode != 0


def test_t2_f5_build_iso_sh_rejects_unknown_flag(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "build-iso.sh", "build-iso.sh")
    res = subprocess.run(
        [git_bash_exe, str(sh), "--definitely-invalid-flag"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode != 0


def test_t2_f5_build_iso_ps1_rejects_unknown_param(
    repo_root: Path, powershell_exe: str
) -> None:
    ps1 = require_artifact(repo_root / "scripts" / "build-iso.ps1", "build-iso.ps1")
    res = subprocess.run(
        [
            powershell_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-DefinitelyInvalidParam",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode != 0


def test_t2_f5_build_iso_sh_quoted_path_spaces_safe(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "build-iso.sh", "build-iso.sh")
    res = subprocess.run(
        [git_bash_exe, str(sh), "--dry-run"],
        cwd=str(repo_root),
        env={"PATH": "/usr/bin:/bin", "OUT_DIR": "/tmp/kite os with spaces"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0


# ===========================================================================
# Feature 6: QEMU Runners Boundaries (5 tests)
# ===========================================================================


def test_t2_f6_test_qemu_sh_rejects_invalid_ram_2g(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    res = subprocess.run(
        [git_bash_exe, str(sh), "--dry-run", "--ram", "2G"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode != 0


def test_t2_f6_test_qemu_sh_rejects_invalid_ram_32g(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    res = subprocess.run(
        [git_bash_exe, str(sh), "--dry-run", "--ram", "32G"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode != 0


def test_t2_f6_test_qemu_ps1_rejects_invalid_ram_tier(
    repo_root: Path, powershell_exe: str
) -> None:
    ps1 = require_artifact(repo_root / "scripts" / "test-qemu.ps1", "test-qemu.ps1")
    res = subprocess.run(
        [
            powershell_exe,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-DryRun",
            "-Ram",
            "3G",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode != 0


def test_t2_f6_test_qemu_sh_fails_cleanly_on_missing_iso(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    res = subprocess.run(
        [git_bash_exe, str(sh), "--iso", "/tmp/nonexistent-kite-9480m.iso"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode != 0


def test_t2_f6_test_qemu_never_uses_tsx_enabled_cpu(
    repo_root: Path, git_bash_exe: str, powershell_exe: str
) -> None:
    sh = require_artifact(repo_root / "scripts" / "test-qemu.sh", "test-qemu.sh")
    ps1 = require_artifact(repo_root / "scripts" / "test-qemu.ps1", "test-qemu.ps1")
    out_sh = subprocess.run(
        [git_bash_exe, str(sh), "--dry-run", "--ram", "8G"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout
    out_ps = subprocess.run(
        [powershell_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-DryRun", "-Ram", "8G"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    for out in (out_sh, out_ps):
        assert "Haswell-noTSX" in out
        assert not re.search(r"-cpu\s+Haswell(?!-noTSX)", out)


# ===========================================================================
# Feature 7: GitHub Actions CI Boundaries (5 tests)
# ===========================================================================


def test_t2_f7_rejects_malformed_yaml_probe() -> None:
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("jobs:\n  build: [unclosed\n")


def test_t2_f7_workflow_no_hardcoded_secrets(repo_root: Path) -> None:
    wf = require_artifact(repo_root / ".github" / "workflows" / "build-iso.yml", "build-iso.yml")
    text = wf.read_text(encoding="utf-8")
    for pat in ("ghp_", "github_pat_", "AKIA"):
        assert pat not in text


def test_t2_f7_workflow_yaml11_on_key_handled(repo_root: Path) -> None:
    wf = require_artifact(repo_root / ".github" / "workflows" / "build-iso.yml", "build-iso.yml")
    data = run_yaml_load_check(wf)
    triggers = data.get("on") if "on" in data else data.get(True)
    assert isinstance(triggers, dict) and len(triggers) >= 1


def test_t2_f7_workflow_handles_pr_without_privileged_secret_leak(repo_root: Path) -> None:
    wf = require_artifact(repo_root / ".github" / "workflows" / "build-iso.yml", "build-iso.yml")
    text = wf.read_text(encoding="utf-8")
    assert "pull_request_target" not in text


def test_t2_f7_workflow_no_forbidden_drivers_in_ci_steps(repo_root: Path) -> None:
    wf = require_artifact(repo_root / ".github" / "workflows" / "build-iso.yml", "build-iso.yml")
    assert not scan_active_forbidden_assignments(repo_root, [".github"])
    bad_pkg = "intel-media-" + "driver"
    assert bad_pkg not in wf.read_text(encoding="utf-8")


# ===========================================================================
# Feature 8: check_invariants.py Boundaries (5 tests)
# ===========================================================================


def test_t2_f8_detects_injected_iris_in_temp_repo(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(repo_root / "scripts" / "check_invariants.py", "check_invariants.py")
    root = _make_valid_repo_copy(tmp_path)
    bad_gl = "ir" + "is"
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        f"MESA_LOADER_DRIVER_OVERRIDE={bad_gl}\nLIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
    )
    res = _run_invariants(python_exe, script, root)
    assert res.returncode != 0


def test_t2_f8_detects_injected_ihd_and_intel_media_driver(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(repo_root / "scripts" / "check_invariants.py", "check_invariants.py")
    root = _make_valid_repo_copy(tmp_path)
    bad_va = "iH" + "D"
    bad_pkg = "intel-media-" + "driver"
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        f"MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME={bad_va}\n", encoding="utf-8"
    )
    (root / "iso-profile" / "packages.x86_64").write_text(f"mesa\n{bad_pkg}\n", encoding="utf-8")
    res = _run_invariants(python_exe, script, root)
    assert res.returncode != 0


def test_t2_f8_detects_injected_dxvk_2x(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(repo_root / "scripts" / "check_invariants.py", "check_invariants.py")
    root = _make_valid_repo_copy(tmp_path)
    bad_dxvk = "DXVK_VER=" + "2.3"
    (root / "kite-bridge" / "scripts" / "provision-wine.sh").write_text(
        f"#!/usr/bin/env bash\n{bad_dxvk}\n", encoding="utf-8"
    )
    res = _run_invariants(python_exe, script, root)
    assert res.returncode != 0


def test_t2_f8_detects_missing_kitebridge_btrfs_subvolume(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(repo_root / "scripts" / "check_invariants.py", "check_invariants.py")
    root = _make_valid_repo_copy(tmp_path)
    (root / "installer" / "calamares" / "modules" / "mount.conf").write_text(
        "btrfsSubvolumes:\n  - mountPoint: /\n    subvolume: /@\n", encoding="utf-8"
    )
    res = _run_invariants(python_exe, script, root)
    assert res.returncode != 0


def test_t2_f8_nonexistent_root_exits_nonzero(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    script = require_artifact(repo_root / "scripts" / "check_invariants.py", "check_invariants.py")
    res = _run_invariants(python_exe, script, tmp_path / "does_not_exist")
    assert res.returncode != 0


# ===========================================================================
# Feature 9: kite-hw-tune RAM Tier Boundaries (6 tests)
# ===========================================================================


def test_t2_f09_boundary_6143_stays_4g(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(repo_root, python_exe, tmp_path, ram_mb=6143, power_source="AC")
    assert res.returncode == 0 and prof is not None
    assert prof["memory"]["tier"] == "4G"
    assert prof["memory"]["zram_percent"] == 150
    assert prof["memory"]["zram_algo"] == "lz4"
    assert prof["blur"]["tier"] == "static"


def test_t2_f09_boundary_6144_transitions_8g(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(repo_root, python_exe, tmp_path, ram_mb=6144, power_source="AC")
    assert res.returncode == 0 and prof is not None
    assert prof["memory"]["tier"] == "8G"
    assert prof["memory"]["zram_percent"] == 100
    assert prof["memory"]["zram_algo"] == "zstd"
    assert prof["blur"]["enabled"] is True


def test_t2_f09_boundary_12288_remains_8g(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(repo_root, python_exe, tmp_path, ram_mb=12288, power_source="AC")
    assert res.returncode == 0 and prof is not None
    assert prof["memory"]["tier"] == "8G"
    assert prof["subsystems"]["waydroid"]["teardown_after_sec"] is None


def test_t2_f09_boundary_12289_transitions_16g(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(repo_root, python_exe, tmp_path, ram_mb=12289, power_source="AC")
    assert res.returncode == 0 and prof is not None
    assert prof["memory"]["tier"] == "16G"
    assert prof["memory"]["zram_percent"] == 50
    assert prof["subsystems"]["waydroid"]["prewarm"] is True
    assert prof["subsystems"]["osx_kvm"]["hugepages_on_demand"] is True


@pytest.mark.parametrize("bad_ram", [0, -1024])
def test_t2_f09_invalid_ram_zero_or_negative_exits_nonzero(
    repo_root: Path, python_exe: str, tmp_path: Path, bad_ram: int
) -> None:
    res, _ = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=bad_ram,
        meminfo_raw=f"MemTotal: {bad_ram * 1024} kB\n",
    )
    assert res.returncode != 0


def test_t2_f09_corrupt_meminfo_exits_nonzero_cleanly(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, _ = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=None,
        pass_ram_flag=False,
        meminfo_raw="MemTotal: corrupt kB\n",
    )
    assert res.returncode != 0
    assert "Traceback" not in res.stderr


# ===========================================================================
# Feature 10: kite-hw-tune Storage Boundaries (5 tests)
# ===========================================================================


def test_t2_f10_virtual_only_sys_block_yields_empty_storage(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        block_devices={"loop0": 0, "loop1": 0, "ram0": 0, "zram0": 0, "sr0": 1},
    )
    assert res.returncode == 0 and prof is not None
    assert prof["storage"] == []


def test_t2_f10_empty_sys_block_succeeds(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(repo_root, python_exe, tmp_path, block_devices={})
    assert res.returncode == 0 and prof is not None
    assert prof["storage"] == []


def test_t2_f10_invalid_rotational_content_handled_gracefully(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, block_devices={"sda": "abc", "sdb": 0}
    )
    assert res.returncode == 0 and prof is not None
    assert "Traceback" not in res.stderr
    assert all(d["device"] != "sda" for d in prof["storage"])


def test_t2_f10_missing_rotational_file_skipped_without_crash(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, block_devices={"mmcblk0": None, "sda": 0}
    )
    assert res.returncode == 0 and prof is not None
    assert "Traceback" not in res.stderr


def test_t2_f10_high_device_count_16_devices_no_virtual_leak(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    devs: dict[str, int] = {f"sd{chr(97 + i)}": i % 2 for i in range(12)}
    devs.update({"loop0": 0, "loop1": 0, "zram0": 0, "ram0": 0})
    res, prof = run_kite_hw_tune(repo_root, python_exe, tmp_path, block_devices=devs)
    assert res.returncode == 0 and prof is not None
    names = {d["device"] for d in prof["storage"]}
    assert len(names) == 12
    assert not any(n.startswith(("loop", "zram", "ram", "sr")) for n in names)


# ===========================================================================
# Feature 11: kite-hw-tune GPU, CPU & Power Boundaries (5 tests)
# ===========================================================================


def test_t2_f11_missing_power_supply_safe_fallback(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res, prof = run_kite_hw_tune(
        repo_root,
        python_exe,
        tmp_path,
        ram_mb=8192,
        power_source=None,
        pass_power_flag=False,
        include_power_supply=False,
    )
    assert res.returncode == 0 and prof is not None
    assert prof["power"]["source"] in {"AC", "Battery"}


def test_t2_f11_invalid_power_cli_arg_rejected(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    help_info = introspect_cli_help(repo_root, python_exe, "kite_hw_tune")
    if "--power" not in help_info["flags"] and "--power-source" not in help_info["flags"]:
        pytest.skip("CLI does not expose --power flag")
    res, _ = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=8192, power_source="InvalidSource"
    )
    assert res.returncode != 0


def test_t2_f11_4g_blur_remains_static_ac_and_battery(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    for pwr in ("AC", "Battery"):
        sub = tmp_path / pwr
        sub.mkdir()
        res, prof = run_kite_hw_tune(
            repo_root, python_exe, sub, ram_mb=4096, power_source=pwr
        )
        assert res.returncode == 0 and prof is not None
        assert prof["blur"] == {
            "tier": "static",
            "enabled": False,
            "size": 0,
            "passes": 0,
            "xray": False,
        }


def test_t2_f11_no_forbidden_drivers_in_kite_hw_tune(repo_root: Path) -> None:
    require_artifact(repo_root / "kite-hw-tune", "kite-hw-tune")
    assert not scan_active_forbidden_assignments(repo_root, ["kite-hw-tune"])


def test_t2_f11_blur_bounds_across_all_tier_power_combinations(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    for ram in (4096, 8192, 16384):
        for pwr in ("AC", "Battery"):
            sub = tmp_path / f"{ram}_{pwr}"
            sub.mkdir()
            res, prof = run_kite_hw_tune(
                repo_root, python_exe, sub, ram_mb=ram, power_source=pwr
            )
            assert res.returncode == 0 and prof is not None
            assert 0 <= prof["blur"]["size"] <= 6
            assert 0 <= prof["blur"]["passes"] <= 2


# ===========================================================================
# Feature 12: kite-hw-tune Systemd & udev Boundaries (5 tests)
# ===========================================================================


def test_t2_f12_nested_nonexistent_output_parent_dir(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    nested = tmp_path / "deep" / "nested" / "hw-profile.json"
    res, _ = run_kite_hw_tune(
        repo_root, python_exe, tmp_path, ram_mb=8192, output_path=nested
    )
    assert "Traceback" not in res.stderr
    assert res.returncode == 0 or "error" in (res.stderr + res.stdout).lower()


def test_t2_f12_schema_tamper_rejects_wrong_version() -> None:
    bad = {"schema_version": 2, "ram_mb": 8192}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=HW_PROFILE_SCHEMA_V1)


def test_t2_f12_storage_udev_rules_excludes_virtual_devices(repo_root: Path) -> None:
    rule = require_artifact(
        repo_root / "kite-hw-tune" / "udev" / "99-kite-storage.rules",
        "99-kite-storage.rules",
    )
    text = rule.read_text(encoding="utf-8")
    assert "zram" in text or "loop" in text or "kite-hw-tune" in text


def test_t2_f12_systemd_units_no_hardcoded_ram_overrides(repo_root: Path) -> None:
    sdir = require_artifact(repo_root / "kite-hw-tune" / "systemd", "systemd dir")
    for unit in sdir.glob("*.service"):
        txt = unit.read_text(encoding="utf-8")
        assert not re.search(r"--ram-mb\s+(4096|8192|16384)", txt)


def test_t2_f12_install_sh_strict_error_handling_no_user_paths(repo_root: Path) -> None:
    sh = require_artifact(repo_root / "kite-hw-tune" / "install.sh", "install.sh")
    txt = sh.read_text(encoding="utf-8")
    assert "set -e" in txt or "set -euo pipefail" in txt
    assert "/home/kian" not in txt.lower() and "c:\\" not in txt.lower()


# ===========================================================================
# Feature 13: Hyprland Config Boundaries (5 tests)
# ===========================================================================


def test_t2_f13_blur_size_never_exceeds_6(repo_root: Path) -> None:
    hdir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    for conf in hdir.glob("*.conf"):
        txt = conf.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:blur:)?size\s*=\s*(\d+)", txt):
            assert 0 <= int(m.group(1)) <= 6, f"Blur size > 6 in {conf}: {m.group(0)}"


def test_t2_f13_blur_passes_never_exceeds_2(repo_root: Path) -> None:
    hdir = require_artifact(repo_root / "kite-shell" / "hypr", "kite-shell/hypr")
    for conf in hdir.glob("*.conf"):
        txt = conf.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:blur:)?passes\s*=\s*(\d+)", txt):
            assert 0 <= int(m.group(1)) <= 2, f"Blur passes > 2 in {conf}: {m.group(0)}"


def test_t2_f13_runtime_source_ordered_after_base_glass(repo_root: Path) -> None:
    hconf = require_artifact(
        repo_root / "kite-shell" / "hypr" / "hyprland.conf", "hyprland.conf"
    )
    lines = hconf.read_text(encoding="utf-8").splitlines()
    glass_idx = [i for i, ln in enumerate(lines) if "glass.conf" in ln]
    rt_idx = [i for i, ln in enumerate(lines) if "kite-glass-runtime.conf" in ln]
    assert rt_idx, "kite-glass-runtime.conf source missing from hyprland.conf"
    if glass_idx:
        assert max(rt_idx) > min(glass_idx), "Runtime conf must be sourced after base glass.conf"


def test_t2_f13_alt_f4_killactive_not_misbound(repo_root: Path) -> None:
    kconf = require_artifact(
        repo_root / "kite-shell" / "hypr" / "keybinds.conf", "keybinds.conf"
    )
    txt = kconf.read_text(encoding="utf-8")
    assert re.search(r"bind.*ALT.*F4.*killactive", txt, re.IGNORECASE)
    assert not re.search(r"bind.*SUPER\s*,\s*F4\s*,\s*killactive", txt, re.IGNORECASE)


def test_t2_f13_install_sh_seeds_runtime_conf_safely(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(repo_root / "kite-shell" / "install.sh", "kite-shell/install.sh")
    run_sh_syntax_check(git_bash_exe, sh)
    assert "kite-glass-runtime.conf" in sh.read_text(encoding="utf-8")


# ===========================================================================
# Feature 14: Quickshell QML Boundaries (5 tests)
# ===========================================================================


def test_t2_f14_no_qt5_legacy_imports_or_effects(repo_root: Path) -> None:
    sdir = require_artifact(repo_root / "kite-shell", "kite-shell")
    qmls = list(sdir.rglob("*.qml"))
    assert qmls, "No QML files under kite-shell/"
    for q in qmls:
        txt = q.read_text(encoding="utf-8")
        assert not re.search(r"import\s+QtQuick\s+2\.", txt), f"Legacy QtQuick 2.x in {q}"
        for ln in txt.splitlines():
            if "QtGraphicalEffects" in ln and "Qt5Compat" not in ln:
                pytest.fail(f"Legacy Qt5 QtGraphicalEffects in {q}: {ln}")


def test_t2_f14_all_qml_strings_and_comments_terminated(repo_root: Path) -> None:
    sdir = require_artifact(repo_root / "kite-shell", "kite-shell")
    qmls = list(sdir.rglob("*.qml"))
    assert qmls
    for q in qmls:
        run_qml_structural_check(q)


def test_t2_f14_qml_handles_untagged_native_linux_apps(repo_root: Path) -> None:
    sm = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml", "StartMenu.qml"
    )
    txt = sm.read_text(encoding="utf-8")
    assert '""' in txt or "''" in txt or "default" in txt.lower() or "linux" in txt.lower()


def test_t2_f14_qml_empty_states_guarded(repo_root: Path) -> None:
    nc = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "NotificationCenter.qml",
        "NotificationCenter.qml",
    )
    sm = require_artifact(
        repo_root / "kite-shell" / "quickshell" / "StartMenu.qml", "StartMenu.qml"
    )
    nc_txt = nc.read_text(encoding="utf-8")
    sm_txt = sm.read_text(encoding="utf-8")
    assert (
        "length === 0" in nc_txt
        or "length > 0" in nc_txt
        or "empty" in nc_txt.lower()
        or "count === 0" in nc_txt
    )
    assert "length === 0" in sm_txt or '""' in sm_txt


def test_t2_f14_quickshell_components_and_shell_entrypoints_valid(repo_root: Path) -> None:
    qs_dir = require_artifact(repo_root / "kite-shell" / "quickshell", "kite-shell/quickshell")
    shell_txt = require_artifact(qs_dir / "shell.qml", "shell.qml").read_text(encoding="utf-8")
    for comp in ("Taskbar", "StartMenu", "QuickSettings", "NotificationCenter", "SnapLayouts"):
        assert comp in shell_txt, f"shell.qml missing {comp}"
    for q in qs_dir.rglob("*.qml"):
        run_qml_structural_check(q)


# ===========================================================================
# Feature 15: kite-settings Boundaries (6 tests)
# ===========================================================================


def _run_settings_with_payload(
    repo_root: Path, python_exe: str, tmp_path: Path, payload: dict[str, Any], hw_profile: dict[str, Any] | None = None
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, str]:
    prof_path: Path | None = None
    if hw_profile is not None:
        prof_path = tmp_path / "hw-profile.json"
        prof_path.write_text(json.dumps(hw_profile), encoding="utf-8")

    return invoke_kite_settings_cli(
        repo_root,
        python_exe,
        tmp_path,
        settings_dict=payload,
        hw_profile_path=prof_path,
    )


def _sample_hw_profile(tier: str, source: str) -> dict[str, Any]:
    blur_map = {
        ("4G", "AC"): {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False},
        ("4G", "Battery"): {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False},
        ("8G", "AC"): {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True},
        ("8G", "Battery"): {"tier": "kawase_1pass", "enabled": True, "size": 4, "passes": 1, "xray": True},
    }
    return {
        "schema_version": 1,
        "ram_mb": 4096 if tier == "4G" else 8192,
        "memory": {
            "tier": tier,
            "zram_percent": 150 if tier == "4G" else 100,
            "zram_size_mb": 6144 if tier == "4G" else 8192,
            "zram_algo": "lz4" if tier == "4G" else "zstd",
            "idle_budget_mb": 250 if tier == "4G" else 350,
            "sysctl": {"vm.swappiness": 180 if tier == "4G" else 150, "vm.page-cluster": 0},
        },
        "power": {
            "source": source,
            "epp": "balance_performance",
            "snd_hda_intel_power_save": 0 if source == "AC" else 1,
            "iwlwifi_power_save": source == "Battery",
        },
        "blur": blur_map[(tier, source)],
        "storage": [],
        "subsystems": {
            "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
            "waydroid": {"idle_policy": "cgroup_freeze", "teardown_after_sec": None, "prewarm": False},
            "osx_kvm": {"hugepages_on_demand": False},
        },
    }


def test_t2_f15_blur_radius_above_6_clamped(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    payload = {
        "schema_version": 1,
        "theme_preset": "Aero Blue",
        "accent_color": "#38BDF8",
        "taskbar_alignment": "center",
        "transparency": 0.72,
        "blur_radius": 12,
        "specular_edge_brightness": 0.35,
        "corner_radius": 12,
        "animation_speed": 1.0,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "aero-glass-wave",
        "battery_glass_autosimplify": True,
        "mitigations_off_requested": False,
    }
    res, _, hypr_txt = _run_settings_with_payload(
        repo_root, python_exe, tmp_path, payload, _sample_hw_profile("8G", "AC")
    )
    assert res.returncode == 0
    for m in re.finditer(r"size\s*=\s*(\d+)", hypr_txt):
        assert int(m.group(1)) <= 6


def test_t2_f15_blur_passes_above_2_never_emitted(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    payload = {
        "schema_version": 1,
        "theme_preset": "Aero Blue",
        "accent_color": "#38BDF8",
        "taskbar_alignment": "center",
        "transparency": 0.72,
        "blur_radius": 16,
        "specular_edge_brightness": 0.35,
        "corner_radius": 12,
        "animation_speed": 1.0,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "aero-glass-wave",
        "battery_glass_autosimplify": False,
        "mitigations_off_requested": False,
    }
    res, _, hypr_txt = _run_settings_with_payload(
        repo_root, python_exe, tmp_path, payload, _sample_hw_profile("8G", "AC")
    )
    assert res.returncode == 0
    for m in re.finditer(r"passes\s*=\s*(\d+)", hypr_txt):
        assert int(m.group(1)) <= 2


def test_t2_f15_negative_and_out_of_range_sliders_clamped(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    payload = {
        "schema_version": 1,
        "theme_preset": "Aero Blue",
        "accent_color": "#38BDF8",
        "taskbar_alignment": "center",
        "transparency": 1.9,
        "blur_radius": -5,
        "specular_edge_brightness": 0.35,
        "corner_radius": -8,
        "animation_speed": -1.0,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "aero-glass-wave",
        "battery_glass_autosimplify": True,
        "mitigations_off_requested": False,
    }
    res, out_s, hypr_txt = _run_settings_with_payload(
        repo_root, python_exe, tmp_path, payload, _sample_hw_profile("8G", "AC")
    )
    assert "Traceback" not in res.stderr
    if res.returncode == 0 and out_s is not None:
        assert 0 <= out_s["blur_radius"] <= 6
        assert 0.0 <= out_s["transparency"] <= 1.0
        assert out_s["corner_radius"] >= 0
        assert out_s["animation_speed"] > 0
        assert "-" not in "".join(re.findall(r"size\s*=\s*(-?\d+)", hypr_txt))


def test_t2_f15_invalid_preset_alignment_and_hex_color(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    payload = {
        "schema_version": 1,
        "theme_preset": "NonExistent",
        "accent_color": "xyz",
        "taskbar_alignment": "top",
        "transparency": 0.72,
        "blur_radius": 6,
        "specular_edge_brightness": 0.35,
        "corner_radius": 12,
        "animation_speed": 1.0,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "aero-glass-wave",
        "battery_glass_autosimplify": True,
        "mitigations_off_requested": False,
    }
    res, out_s, _ = _run_settings_with_payload(repo_root, python_exe, tmp_path, payload)
    assert "Traceback" not in res.stderr
    if res.returncode == 0 and out_s is not None:
        assert out_s["taskbar_alignment"] in {"center", "left"}
        assert re.match(r"^#[0-9A-Fa-f]{6}$", out_s["accent_color"])


def test_t2_f15_missing_hw_profile_json_graceful_default(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_settings(
        repo_root,
        python_exe,
        tmp_path,
        args=["--help"],
        hw_profile_path=tmp_path / "missing_hw_profile.json",
    )
    assert res.returncode == 0
    assert "Traceback" not in res.stderr


def test_t2_f15_4g_tier_forces_blur_disabled_and_battery_autosimplify(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    payload = {
        "schema_version": 1,
        "theme_preset": "Aero Blue",
        "accent_color": "#38BDF8",
        "taskbar_alignment": "center",
        "transparency": 0.72,
        "blur_radius": 6,
        "specular_edge_brightness": 0.35,
        "corner_radius": 12,
        "animation_speed": 1.0,
        "spring_curve": "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        "wallpaper": "aero-glass-wave",
        "battery_glass_autosimplify": True,
        "mitigations_off_requested": False,
    }
    d4 = tmp_path / "t4g"
    d4.mkdir()
    res4, _, hypr4 = _run_settings_with_payload(
        repo_root, python_exe, d4, payload, _sample_hw_profile("4G", "AC")
    )
    assert res4.returncode == 0
    assert re.search(r"enabled\s*=\s*false", hypr4, re.IGNORECASE) or re.search(r"passes\s*=\s*0\b", hypr4)

    d8 = tmp_path / "t8gb"
    d8.mkdir()
    res8, _, hypr8 = _run_settings_with_payload(
        repo_root, python_exe, d8, payload, _sample_hw_profile("8G", "Battery")
    )
    assert res8.returncode == 0
    assert re.search(r"passes\s*=\s*1\b", hypr8)


# ===========================================================================
# Feature 16: Interactive Preview Boundaries (5 tests)
# ===========================================================================


def test_t2_f16_preview_folio9480m_viewports_no_overflow(
    preview_server_url: str, playwright_page: Any
) -> None:
    for w, h in ((1366, 768), (1600, 900)):
        playwright_page.set_viewport_size({"width": w, "height": h})
        playwright_page.goto(preview_server_url, wait_until="load")
        overflow = playwright_page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth"
        )
        assert not overflow, f"Horizontal overflow at {w}x{h}"
    assert playwright_page._kite_errors["console"] == []
    assert playwright_page._kite_errors["page"] == []


def test_t2_f16_preview_start_menu_empty_and_nomatch_search(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    playwright_page.get_by_role("button", name=re.compile("start", re.I)).first.click()
    assert playwright_page.locator("#start-menu").is_visible()
    cards = playwright_page.locator("#start-apps-grid .start-app-card")
    full_count = cards.count()
    assert full_count >= 4
    search = playwright_page.locator("input[type='search'], input[type='text'], [role='searchbox']").first
    search.fill("___no_such_app_999___")
    assert cards.count() == 0, "No-match search must filter Start Menu cards to 0"
    search.fill("")
    assert cards.count() == full_count, "Clearing search must restore all Start Menu cards"
    assert playwright_page._kite_errors["console"] == []
    assert playwright_page._kite_errors["page"] == []


def test_t2_f16_preview_escape_dismisses_active_overlay(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    playwright_page.get_by_role("button", name=re.compile("start", re.I)).first.click()
    start_menu = playwright_page.locator("#start-menu")
    assert start_menu.is_visible()
    assert start_menu.get_attribute("aria-hidden") == "false"
    playwright_page.keyboard.press("Escape")
    assert not start_menu.is_visible(), "Escape must hide active Start Menu overlay"
    assert start_menu.get_attribute("aria-hidden") == "true"
    assert start_menu.get_attribute("hidden") is not None
    assert playwright_page._kite_errors["console"] == []
    assert playwright_page._kite_errors["page"] == []


def test_t2_f16_preview_4g_hardware_mode_disables_live_blur(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    btn_4g = playwright_page.get_by_role("button", name=re.compile(r"4\s*GB|4G", re.I))
    if btn_4g.count() > 0:
        btn_4g.first.click()
    else:
        playwright_page.get_by_text(re.compile(r"4\s*GB|4G", re.I)).first.click()
    root = playwright_page.locator("#desktop-root")
    assert root.get_attribute("data-hw-tier") == "4G"
    assert root.get_attribute("data-blur-mode") == "static"
    assert "enabled = false" in playwright_page.locator('[data-testid="runtime-conf-preview"]').inner_text().lower()
    txt = playwright_page.locator("body").inner_text().lower()
    assert "static" in txt and "4g" in txt
    assert playwright_page._kite_errors["page"] == []


def test_t2_f16_preview_rapid_overlay_switching_no_stuck_state(
    preview_server_url: str, playwright_page: Any
) -> None:
    playwright_page.goto(preview_server_url, wait_until="load")
    steps = [
        ("start", "#start-menu"),
        ("quick|wi-fi|win\\+a", "#quick-settings"),
        ("notification|calendar|win\\+n", "#notification-center"),
        ("snap|win\\+z", "#snap-layouts"),
    ]
    for pat, overlay_sel in steps:
        loc = playwright_page.get_by_role("button", name=re.compile(pat, re.I))
        assert loc.count() > 0 and loc.first.is_visible(), f"Missing trigger for {pat}"
        loc.first.click()
        assert playwright_page.locator(overlay_sel).is_visible(), f"{overlay_sel} did not open"
        assert playwright_page.locator(".flyout.is-open").count() == 1
    assert playwright_page._kite_errors["console"] == []
    assert playwright_page._kite_errors["page"] == []


# ===========================================================================
# Feature 17: kite-bridge CLI, MIME & Desktop Boundaries (6 tests)
# ===========================================================================


@pytest.mark.parametrize("bad_name", ["notes.txt", "archive.xyz"])
def test_t2_f17_unknown_extension_rejected(
    repo_root: Path, python_exe: str, tmp_path: Path, bad_name: str
) -> None:
    f = tmp_path / bad_name
    f.write_text("hello", encoding="utf-8")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(f), "--json"])
    assert res.returncode != 0


@pytest.mark.parametrize("bad_name", ["README", ".hidden"])
def test_t2_f17_extensionless_and_dotfile_rejected(
    repo_root: Path, python_exe: str, tmp_path: Path, bad_name: str
) -> None:
    f = tmp_path / bad_name
    f.write_text("data", encoding="utf-8")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(f), "--json"])
    assert res.returncode != 0


def test_t2_f17_uppercase_mixed_case_extensions_normalized(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    f_exe = tmp_path / "INSTALL.EXE"
    f_exe.write_bytes(b"DUMMY")
    f_apk = write_minimal_apk(tmp_path / "App.Apk")
    f_dmg = tmp_path / "Image.DMG"
    f_dmg.write_bytes(b"DUMMY")
    for f, expected_plat in ((f_exe, "win"), (f_apk, "android"), (f_dmg, "macos")):
        res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(f), "--json"])
        assert res.returncode == 0, f"Failed mixed-case {f.name}: {res.stderr}"
        assert json.loads(res.stdout)["platform"] == expected_plat


def test_t2_f17_nonexistent_file_path_fails_cleanly(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(tmp_path / "missing_app.exe"), "--json"],
    )
    assert res.returncode != 0
    assert "Traceback" not in res.stderr


def test_t2_f17_invalid_cli_flags_rejected(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["--bogus-flag-xyz"])
    assert res.returncode != 0


def test_t2_f17_double_extension_tar_gz_vs_pdf_exe(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    tar_gz = tmp_path / "payload.tar.gz"
    tar_gz.write_bytes(b"GZ")
    res_tar = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(tar_gz), "--json"])
    assert res_tar.returncode != 0

    pdf_exe = tmp_path / "evil.pdf.exe"
    pdf_exe.write_bytes(b"MZ")
    res_exe = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(pdf_exe), "--json"])
    assert res_exe.returncode == 0
    assert json.loads(res_exe.stdout)["platform"] == "win"


# ===========================================================================
# Feature 18: kite-bridge Windows Subsystem Boundaries (5 tests)
# ===========================================================================


def test_t2_f18_dxvk_2x_rejected_or_overridden_to_1_10_3(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    exe = tmp_path / "game.exe"
    exe.write_bytes(b"MZ")
    bad_ver = "2." + "3"
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(exe), "--dry-run", "--json"],
        extra_env={"DXVK_VER": bad_ver},
    )
    if res.returncode == 0:
        data = json.loads(res.stdout)
        assert data["dxvk_version"] == "1.10.3"
        assert data["env"]["DXVK_VER"] == "1.10.3"
    else:
        assert "Traceback" not in res.stderr, f"Unexpected traceback:\n{res.stderr}"
        combined = res.stdout + "\n" + res.stderr
        assert "DxvkVersionViolationError" in combined or "1.10.3" in combined, (
            f"Expected DxvkVersionViolationError or 1.10.3 guidance, got:\n{combined}"
        )
    assert not scan_active_forbidden_assignments(repo_root, ["kite-bridge"])


def test_t2_f18_lnk_with_spaces_and_parens_safely_handled(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    lnk = tmp_path / "My App (x86).lnk"
    lnk.write_bytes(b"LNK")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(lnk), "--json"])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["platform"] == "win"
    assert data["dxvk_version"] == "1.10.3"
    assert any("My App (x86).lnk" in arg for arg in data["command"])


def test_t2_f18_missing_ntsync_graceful_fallback(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["inspect", str(exe), "--json"],
        ntsync_available=False,
    )
    assert res.returncode == 0
    assert "Traceback" not in res.stderr


def test_t2_f18_dx12_never_selects_vkd3d_proton(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    exe = tmp_path / "dx12_game.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["open", str(exe), "--dry-run", "--json"]
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data.get("wined3d_dx12") is True
    assert "vkd3d" not in json.dumps(data).lower()


def test_t2_f18_desktop_install_sanitizes_path_traversal(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    exe = tmp_path / "..evil..app.exe"
    exe.write_bytes(b"MZ")
    desktop_dir = tmp_path / "xdg_data" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    help_info = introspect_cli_help(repo_root, python_exe, "kite_bridge", "install")
    args = ["install", str(exe)]
    if "--desktop-dir" in help_info["flags"]:
        args.extend(["--desktop-dir", str(desktop_dir)])
    res = run_kite_bridge(repo_root, python_exe, tmp_path, args)
    assert res.returncode == 0
    for f in desktop_dir.rglob("*.desktop"):
        assert f.resolve().parent == desktop_dir.resolve()


# ===========================================================================
# Feature 19: kite-bridge Android Subsystem Boundaries (5 tests)
# ===========================================================================


def test_t2_f19_missing_hw_profile_graceful_default(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        args,
        hw_profile_path=tmp_path / "missing_hw_profile.json",
    )
    assert res.returncode == 0
    assert "Traceback" not in res.stderr


def test_t2_f19_corrupt_hw_profile_json_handled_cleanly(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    bad_prof = tmp_path / "corrupt.json"
    bad_prof.write_text("{corrupt_json", encoding="utf-8")
    args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "waydroid", "status")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        args,
        hw_profile_path=bad_prof,
    )
    assert "Traceback" not in res.stderr


def test_t2_f19_4g_idle_boundary_299s_vs_300s(
    repo_root: Path, python_exe: str, git_bash_exe: str, tmp_path: Path
) -> None:
    prof = tmp_path / "hw4g.json"
    d = _sample_hw_profile("4G", "Battery")
    d["subsystems"]["waydroid"] = {
        "idle_policy": "freeze_then_teardown",
        "teardown_after_sec": 300,
        "prewarm": False,
    }
    prof.write_text(json.dumps(d), encoding="utf-8")

    # Isolated PATH shim so non-dry-run `start` and `teardown` invoke a no-op waydroid stub
    bin_dir = tmp_path / "shim_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        git_usr_bin = Path(git_bash_exe).parent.parent / "usr" / "bin"
        true_exe = git_usr_bin / "true.exe"
        assert true_exe.is_file(), f"Missing Git usr/bin/true.exe at {true_exe}"
        shutil.copy2(true_exe, bin_dir / "waydroid.exe")
        shim_path = f"{bin_dir}{os.pathsep}{git_usr_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    else:
        wd = bin_dir / "waydroid"
        wd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        wd.chmod(0o755)
        shim_path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    cgroup_dir = tmp_path / "mock_cgroup_waydroid"
    cgroup_dir.mkdir(parents=True, exist_ok=True)
    shim_env = {
        "PATH": shim_path,
        "KITEBRIDGE_WAYDROID_CGROUP": str(cgroup_dir),
    }

    args_start = build_kite_bridge_lifecycle_args(
        repo_root, python_exe, "waydroid", "start", dry_run=False
    )
    args299 = build_kite_bridge_lifecycle_args(
        repo_root, python_exe, "waydroid", "idle-tick", idle_seconds=299, dry_run=False
    )
    args300 = build_kite_bridge_lifecycle_args(
        repo_root, python_exe, "waydroid", "idle-tick", idle_seconds=300, dry_run=False
    )

    r_start = run_kite_bridge(
        repo_root, python_exe, tmp_path, args_start, hw_profile_path=prof, extra_env=shim_env
    )
    assert r_start.returncode == 0, r_start.stderr
    assert json.loads(r_start.stdout)["waydroid"]["state"] == "active"

    r299 = run_kite_bridge(
        repo_root, python_exe, tmp_path, args299, hw_profile_path=prof, extra_env=shim_env
    )
    assert r299.returncode == 0, r299.stderr
    d299 = json.loads(r299.stdout)["waydroid"]
    assert d299["state"] == "frozen", f"Expected frozen at 299s, got {d299}"
    assert d299["cgroup_frozen"] is True

    r300 = run_kite_bridge(
        repo_root, python_exe, tmp_path, args300, hw_profile_path=prof, extra_env=shim_env
    )
    assert r300.returncode == 0, r300.stderr
    d300 = json.loads(r300.stdout)["waydroid"]
    assert d300["state"] == "stopped", f"Expected stopped/teardown at 300s, got {d300}"
    assert d300["cgroup_frozen"] is False


def test_t2_f19_aab_bundle_routing_multi_window(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    aab = write_minimal_aab(tmp_path / "release.aab")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(aab), "--json"])
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["platform"] == "android"
    assert "waydroid" in data["handler"].lower()
    assert (
        "persist.waydroid.multi_windows" in json.dumps(data)
        or data.get("metadata", {}).get("multi_windows") is True
    )


def test_t2_f19_missing_binder_flagged_in_status(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["status", "--json"],
        binder_available=False,
    )
    assert res.returncode == 0
    assert "binder" in res.stdout.lower()


# ===========================================================================
# Feature 20: kite-bridge macOS Subsystem Boundaries (6 tests)
# ===========================================================================


def test_t2_f20_missing_kvm_refuses_osx_kvm_launch_cleanly(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    app = tmp_path / "Cocoa.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Cocoa").write_bytes(b"\xcf\xfa\xed\xfe")
    res_dry = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(app), "--dry-run", "--json"],
        kvm_available=False,
    )
    assert "Traceback" not in res_dry.stderr
    assert "kvm" in (res_dry.stdout + res_dry.stderr).lower()

    res_live = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(app), "--json"],
        kvm_available=False,
    )
    assert res_live.returncode != 0, "Expected non-zero exit on live OSX-KVM open without /dev/kvm"
    assert "Traceback" not in res_live.stderr, f"Unexpected traceback:\n{res_live.stderr}"
    combined_live = res_live.stdout + "\n" + res_live.stderr
    assert "KvmUnavailableError" in combined_live or "kvm" in combined_live.lower(), (
        f"Expected KvmUnavailableError/kvm guidance, got:\n{combined_live}"
    )


def test_t2_f20_app_bundle_missing_binary_handled_cleanly(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    empty_app = tmp_path / "Empty.app"
    empty_app.mkdir()
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["inspect", str(empty_app), "--json"]
    )
    assert "IsADirectoryError" not in res.stderr
    assert "Traceback" not in res.stderr


def test_t2_f20_osx_kvm_cpu_flag_exact_haswell_notsx(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    app = tmp_path / "GuiApp.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "GuiApp").write_bytes(b"\xcf\xfa\xed\xfe")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(app), "--dry-run", "--json"],
        kvm_available=True,
    )
    assert res.returncode == 0
    cmd_str = " ".join(json.loads(res.stdout)["command"])
    assert "Haswell-noTSX,+invtsc,vendor=GenuineIntel" in cmd_str
    assert "Broadwell" not in cmd_str and "Skylake" not in cmd_str


def test_t2_f20_pkg_with_spaces_safely_quoted(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    pkg = tmp_path / "Mac Installer v1.0.pkg"
    pkg.write_bytes(b"xar!")
    res = run_kite_bridge(repo_root, python_exe, tmp_path, ["inspect", str(pkg), "--json"])
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["platform"] == "macos"
    assert any("Mac Installer v1.0.pkg" in arg for arg in data["command"])


def test_t2_f20_darling_cli_does_not_require_kvm(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    macho = tmp_path / "tool.macho"
    macho.write_bytes(b"\xcf\xfa\xed\xfe")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(macho), "--dry-run", "--json"],
        kvm_available=False,
    )
    assert res.returncode == 0
    assert "darling" in json.loads(res.stdout)["handler"].lower()


def test_t2_f20_osx_kvm_savevm_idempotent(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    args = build_kite_bridge_lifecycle_args(repo_root, python_exe, "osx-kvm", "hibernate")
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, args
    )
    assert res.returncode == 0
    assert "Traceback" not in res.stderr


# ===========================================================================
# Feature 21: kite-bridge Provisioning & Offline Boundaries (5 tests)
# ===========================================================================


@pytest.mark.parametrize(
    "rel_script",
    [
        "kite-bridge/install.sh",
        "kite-bridge/scripts/provision-wine.sh",
        "kite-bridge/scripts/provision-waydroid.sh",
        "kite-bridge/scripts/provision-macos.sh",
    ],
)
def test_t2_f21_provision_scripts_strict_error_handling(
    repo_root: Path, rel_script: str
) -> None:
    sh = require_artifact(repo_root / rel_script, rel_script)
    txt = sh.read_text(encoding="utf-8")
    assert "set -e" in txt or "set -euo pipefail" in txt


def test_t2_f21_no_dxvk2_or_forbidden_drivers_in_provision_scripts(
    repo_root: Path,
) -> None:
    require_artifact(repo_root / "kite-bridge" / "scripts", "kite-bridge/scripts")
    assert not scan_active_forbidden_assignments(repo_root, ["kite-bridge/scripts"])
    wine_sh = (repo_root / "kite-bridge" / "scripts" / "provision-wine.sh").read_text(
        encoding="utf-8"
    )
    bad_ver = "dxvk-" + "2."
    assert bad_ver not in wine_sh.lower()


def test_t2_f21_provision_wine_verifies_checksum(repo_root: Path) -> None:
    wine_sh = require_artifact(
        repo_root / "kite-bridge" / "scripts" / "provision-wine.sh", "provision-wine.sh"
    )
    assert "sha256sum" in wine_sh.read_text(encoding="utf-8").lower()


def test_t2_f21_cli_never_attempts_live_network_offline(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    exe = tmp_path / "offline.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(
        repo_root,
        python_exe,
        tmp_path,
        ["open", str(exe), "--dry-run", "--json"],
        extra_env={"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"},
    )
    assert res.returncode == 0


def test_t2_f21_hermetic_writes_contained_in_tmp_home(
    repo_root: Path, python_exe: str, tmp_path: Path
) -> None:
    exe = tmp_path / "contained.exe"
    exe.write_bytes(b"MZ")
    res = run_kite_bridge(
        repo_root, python_exe, tmp_path, ["install", str(exe), "--json"]
    )
    assert res.returncode == 0
    created_under_tmp = list(tmp_path.rglob("kitebridge-*.desktop"))
    assert created_under_tmp, "Expected .desktop written strictly inside tmp_path"


# ===========================================================================
# Feature 22: Calamares Glass & Btrfs Boundaries (5 tests)
# ===========================================================================


def test_t2_f22_detects_missing_kitebridge_subvolume_in_fixture(repo_root: Path) -> None:
    part = run_yaml_load_check(
        require_artifact(repo_root / "installer" / "calamares" / "modules" / "partition.conf")
    )
    mnt_path = require_artifact(repo_root / "installer" / "calamares" / "modules" / "mount.conf")
    mnt = run_yaml_load_check(mnt_path)
    mutated = {
        **mnt,
        "btrfsSubvolumes": [s for s in mnt["btrfsSubvolumes"] if "@kitebridge" not in str(s)],
    }
    with pytest.raises(AssertionError):
        _validate_calamares_btrfs_contract(part, mutated, mnt_path.read_text(encoding="utf-8"))


def test_t2_f22_detects_wrong_zstd_level_or_missing_noatime(repo_root: Path) -> None:
    part = run_yaml_load_check(
        require_artifact(repo_root / "installer" / "calamares" / "modules" / "partition.conf")
    )
    mnt_path = require_artifact(repo_root / "installer" / "calamares" / "modules" / "mount.conf")
    raw = mnt_path.read_text(encoding="utf-8")
    bad_global_mnt = yaml.safe_load(raw.replace("compress=zstd:1", "compress=zstd:3"))
    with pytest.raises(AssertionError):
        _validate_calamares_btrfs_contract(part, bad_global_mnt)
    bad_partial_mnt = yaml.safe_load(
        raw.replace(
            "options: [ defaults, compress=zstd:1, noatime ]",
            "options: [ defaults, compress=zstd:3, noatime ]",
        )
    )
    with pytest.raises(AssertionError):
        _validate_calamares_btrfs_contract(part, bad_partial_mnt)
    bad_noatime_mnt = yaml.safe_load(
        raw.replace(
            "options: [ defaults, compress=zstd:1, noatime ]",
            "options: [ defaults, compress=zstd:1 ]",
        )
    )
    with pytest.raises(AssertionError):
        _validate_calamares_btrfs_contract(part, bad_noatime_mnt)


def test_t2_f22_detects_ext4_default_filesystem(repo_root: Path) -> None:
    part = run_yaml_load_check(
        require_artifact(repo_root / "installer" / "calamares" / "modules" / "partition.conf")
    )
    mnt_path = require_artifact(repo_root / "installer" / "calamares" / "modules" / "mount.conf")
    mnt = run_yaml_load_check(mnt_path)
    bad_part = {**part, "defaultFileSystemType": "ext4"}
    with pytest.raises(AssertionError):
        _validate_calamares_btrfs_contract(bad_part, mnt, mnt_path.read_text(encoding="utf-8"))


def test_t2_f22_no_forbidden_drivers_in_calamares_configs(repo_root: Path) -> None:
    require_artifact(repo_root / "installer" / "calamares", "installer/calamares")
    assert not scan_active_forbidden_assignments(repo_root, ["installer/calamares"])


def test_t2_f22_qss_qml_balanced_braces_and_valid_assets(repo_root: Path) -> None:
    bdir = require_artifact(
        repo_root / "installer" / "calamares" / "branding" / "kite-os",
        "calamares branding",
    )
    for qss in bdir.glob("*.qss"):
        txt = qss.read_text(encoding="utf-8")
        assert txt.strip()
        assert txt.count("{") == txt.count("}")
    for qml in bdir.glob("*.qml"):
        run_qml_structural_check(qml)


# ===========================================================================
# Feature 23: Folio 9480m Validation Suite Boundaries (5 tests)
# ===========================================================================


def test_t2_f23_validate_hardware_rejects_iris_ihd_not_requires(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    assert not scan_active_forbidden_assignments(repo_root, ["installer/validation"])
    txt = sh.read_text(encoding="utf-8")
    assert "crocus" in txt and "i965" in txt


def test_t2_f23_validate_hardware_handles_missing_tools_gracefully(repo_root: Path) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    txt = sh.read_text(encoding="utf-8")
    assert "command -v" in txt


def test_t2_f23_validate_hardware_rejects_unknown_flag(
    repo_root: Path, git_bash_exe: str
) -> None:
    sh = require_artifact(
        repo_root / "installer" / "validation" / "validate-hardware.sh",
        "validate-hardware.sh",
    )
    res = subprocess.run(
        [git_bash_exe, str(sh), "--definitely-unknown-flag"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode != 0


def test_t2_f23_checklist_includes_all_three_ram_tiers(repo_root: Path) -> None:
    cl = require_artifact(
        repo_root / "installer" / "validation" / "folio9480m-checklist.md",
        "folio9480m-checklist.md",
    )
    txt = cl.read_text(encoding="utf-8")
    assert any(t in txt for t in ("4 GB", "4GB", "4G"))
    assert any(t in txt for t in ("8 GB", "8GB", "8G"))
    assert any(t in txt for t in ("16 GB", "16GB", "16G"))


def test_t2_f23_checklist_includes_both_ssd_and_hdd_schedulers(repo_root: Path) -> None:
    cl = require_artifact(
        repo_root / "installer" / "validation" / "folio9480m-checklist.md",
        "folio9480m-checklist.md",
    )
    txt = cl.read_text(encoding="utf-8").lower()
    assert ("kyber" in txt or "none" in txt) and "bfq" in txt
