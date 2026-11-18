from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.tests.m1_helpers import REPO_ROOT

CHECKER = REPO_ROOT / "scripts" / "check_invariants.py"


def _run_checker(root: Path, scope: str = "auto") -> tuple[int, dict]:
    res = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), "--scope", scope, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode, json.loads(res.stdout)


def _make_valid_m1_fixture(root: Path) -> None:
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d").mkdir(parents=True)
    (root / "iso-profile" / "airootfs" / "etc" / "modules-load.d").mkdir(parents=True)
    (root / "iso-profile" / "efiboot" / "loader" / "entries").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)

    (root / "iso-profile" / "airootfs" / "etc" / "environment").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
    )
    (root / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=crocus\nLIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
    )
    (root / "iso-profile" / "packages.x86_64").write_text(
        "mesa\nvulkan-intel\nlibva-intel-driver\nlinux-cachyos\nbtrfs-progs\npipewire\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "pacman.conf").write_text(
        "[options]\nArchitecture = x86_64 x86_64_v3\n[cachyos-v3]\nInclude = /etc/pacman.d/cachyos-v3-mirrorlist\n",
        encoding="utf-8",
    )
    (root / "iso-profile" / "airootfs" / "etc" / "modules-load.d" / "kite-os.conf").write_text(
        "ntsync\nbinder_linux\nzram\n", encoding="utf-8"
    )
    (root / "iso-profile" / "efiboot" / "loader" / "entries" / "kite-os.conf").write_text(
        "options i915.enable_fbc=1 i915.fastboot=1 intel_pstate=active\n", encoding="utf-8"
    )
    (root / "scripts" / "test-qemu.sh").write_text(
        "#!/usr/bin/env bash\nqemu-system-x86_64 -cpu Haswell-noTSX\n", encoding="utf-8"
    )
    (root / "scripts" / "test-qemu.ps1").write_text(
        "$argv = @('-cpu', 'Haswell-noTSX')\n", encoding="utf-8"
    )
    (root / "scripts" / "build-iso.sh").write_text(
        "#!/usr/bin/env bash\necho kite-os-folio9480-x86_64_v3.iso\n", encoding="utf-8"
    )
    (root / "scripts" / "build-iso.ps1").write_text(
        "$iso = 'kite-os-folio9480-x86_64_v3.iso'\n", encoding="utf-8"
    )
    (root / ".github" / "workflows" / "build-iso.yml").write_text(
        'name: CI\n"on": [push]\njobs:\n  validate:\n    runs-on: ubuntu-latest\n',
        encoding="utf-8",
    )


def test_repo_m1_invariants_pass() -> None:
    rc, data = _run_checker(REPO_ROOT, scope="m1")
    assert rc == 0, f"M1 invariants failed: {data}"
    assert data["ok"] is True
    assert data["violations"] == []


def test_empty_root_auto_scope_fails(tmp_path: Path) -> None:
    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    assert data["ok"] is False
    assert any(v["rule"] == "no_active_modules" for v in data["violations"])


def test_scope_full_fails_when_m2_to_m5_missing(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "AGENTS.md").write_bytes((REPO_ROOT / "AGENTS.md").read_bytes())
    skill_dst = tmp_path / ".agents" / "skills" / "kite-os-builder" / "SKILL.md"
    skill_dst.parent.mkdir(parents=True)
    skill_dst.write_bytes((REPO_ROOT / ".agents" / "skills" / "kite-os-builder" / "SKILL.md").read_bytes())
    (tmp_path / "README.md").write_text("# KITE_OS\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='kite-os'\n", encoding="utf-8")

    rc_m1, _ = _run_checker(tmp_path, scope="m1")
    assert rc_m1 == 0
    rc_full, data_full = _run_checker(tmp_path, scope="full")
    assert rc_full == 1
    assert any(v["rule"] == "missing_module" for v in data_full["violations"])


def test_negative_active_iris_and_ihd_and_dxvk2_caught(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "iso-profile" / "packages.x86_64").write_text(
        "mesa\nvulkan-intel\nlibva-intel-driver\nintel-media-driver\nlinux-cachyos\nbtrfs-progs\npipewire\n",
        encoding="utf-8",
    )
    (tmp_path / "iso-profile" / "airootfs" / "etc" / "environment.d" / "99-bad.conf").write_text(
        "MESA_LOADER_DRIVER_OVERRIDE=iris\nLIBVA_DRIVER_NAME=iHD\n", encoding="utf-8"
    )
    (tmp_path / "kite-bridge").mkdir(parents=True)
    (tmp_path / "kite-bridge" / "config.py").write_text(
        'DXVK_VER = "2." + "3"\nOSX_FLAGS = "-cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel"\nWAYDROID = "persist.waydroid.multi_windows"\n',
        encoding="utf-8",
    )

    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    rules = {v["rule"] for v in data["violations"]}
    assert "forbidden_package" in rules
    assert "no_iris" in rules
    assert "no_ihd" in rules
    assert "no_dxvk_2x" in rules


def test_comments_guards_and_tests_do_not_false_positive(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "scripts" / "guard.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# Never use iris or intel-media-driver or iHD or DXVK 2.3\n"
        'if [[ "${LIBVA_DRIVER_NAME:-}" == "iHD" ]]; then\n'
        '  echo "iHD_drv_video.so is forbidden"\n'
        "fi\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "guard.ps1").write_text(
        "<# Block iris, intel-media-driver, iHD, DXVK 2.x #>\n"
        'if ($env:LIBVA_DRIVER_NAME -eq "iHD") { Write-Host "iHD unsupported" }\n',
        encoding="utf-8",
    )
    (tmp_path / "kite-bridge" / "tests").mkdir(parents=True)
    (tmp_path / "kite-bridge" / "bridge.py").write_text(
        '"""Guard against DXVK 2.x and intel-media-driver."""\n'
        'DXVK_VER = "1.10.3"\n'
        'OSX = "-cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel"\n'
        'WD = "persist.waydroid.multi_windows"\n'
        'def validate(drv: str, ver: str) -> None:\n'
        '    if drv == "iris" or drv == "iHD" or ver.startswith("2."):\n'
        '        raise ValueError("DXVK 2.x / iris / iHD unsupported")\n',
        encoding="utf-8",
    )
    (tmp_path / "kite-bridge" / "tests" / "test_negative.py").write_text(
        'BAD = "intel-media-driver"\n', encoding="utf-8"
    )

    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 0, f"Unexpected false positives: {data}"


def test_missing_crocus_or_btrfs_subvolume_caught(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "iso-profile" / "airootfs" / "etc" / "environment").write_text("", encoding="utf-8")
    (tmp_path / "iso-profile" / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf").write_text(
        "LIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
    )
    (tmp_path / "installer" / "calamares" / "modules").mkdir(parents=True)
    (tmp_path / "installer" / "calamares" / "modules" / "mount.conf").write_text(
        "btrfsSubvolumes:\n  - mountPoint: /\n    subvolume: /@\n", encoding="utf-8"
    )

    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    rules = {v["rule"] for v in data["violations"]}
    assert "missing_crocus" in rules
    assert "installer_invariants" in rules


def test_hardened_shell_ps1_redirects_setenv_and_narrowed_guards(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "scripts" / "redirect_bad.sh").write_text(
        "#!/usr/bin/env bash\n"
        'echo "MESA_LOADER_DRIVER_OVERRIDE=iris" >> /etc/environment\n'
        "printf 'LIBVA_DRIVER_NAME=iHD\\n' | tee /etc/environment.d/bad.conf\n"
        'BAD="intel-media-driver" # ==\n',
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "setenv_bad.ps1").write_text(
        '[Environment]::SetEnvironmentVariable("MESA_LOADER_DRIVER_OVERRIDE", "iris", "User")\n'
        '[System.Environment]::SetEnvironmentVariable("LIBVA_DRIVER_NAME", "iHD", "Machine")\n'
        '[Environment]::SetEnvironmentVariable("DXVK_VER", "2.3", "User")\n',
        encoding="utf-8",
    )

    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    rules_by_file: dict[str, set[str]] = {}
    for v in data["violations"]:
        rules_by_file.setdefault(v["file"], set()).add(v["rule"])
    assert {"no_iris", "no_ihd", "forbidden_artifact"} <= rules_by_file["scripts/redirect_bad.sh"]
    assert {"no_iris", "no_ihd", "no_dxvk_2x"} <= rules_by_file["scripts/setenv_bad.ps1"]


def test_hardened_calamares_btrfs_exact_at_and_yaml_comments(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    mod_dir = tmp_path / "installer" / "calamares" / "modules"
    mod_dir.mkdir(parents=True)
    # Missing exact '@' (only '@home' present) and '@' only in a YAML comment
    (mod_dir / "mount.conf").write_text(
        "# subvolume: /@\n"
        "btrfsSubvolumes:\n"
        "  - mountPoint: /home\n    subvolume: /@home\n"
        "  - mountPoint: /var/lib/kitebridge\n    subvolume: /@kitebridge\n"
        "  - mountPoint: /.snapshots\n    subvolume: /@snapshots\n"
        "mountOptions:\n"
        "  - filesystem: btrfs\n    options: [ compress=zstd:1, noatime ]\n",
        encoding="utf-8",
    )
    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    assert any(v["rule"] == "installer_invariants" and "@" in v["message"] for v in data["violations"])

    # Now add exact '@' entry -> passes
    (mod_dir / "mount.conf").write_text(
        "btrfsSubvolumes:\n"
        "  - mountPoint: /\n    subvolume: /@\n"
        "  - mountPoint: /home\n    subvolume: /@home\n"
        "  - mountPoint: /var/lib/kitebridge\n    subvolume: /@kitebridge\n"
        "  - mountPoint: /.snapshots\n    subvolume: /@snapshots\n"
        "mountOptions:\n"
        "  - filesystem: btrfs\n    options: [ compress=zstd:1, noatime ]\n",
        encoding="utf-8",
    )
    rc_ok, data_ok = _run_checker(tmp_path, scope="auto")
    assert rc_ok == 0, f"Valid Calamares layout failed: {data_ok}"


def test_hardened_hyprland_colon_syntax_blur_budget(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    hypr_dir = tmp_path / "kite-shell" / "hypr"
    hypr_dir.mkdir(parents=True)
    (hypr_dir / "glass.conf").write_text(
        "decoration:blur:size = 8\n"
        "decoration:blur:passes = 3\n"
        "decoration:blur:xray = true\n",
        encoding="utf-8",
    )
    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    rules = {v["rule"] for v in data["violations"]}
    assert "blur_size_budget" in rules
    assert "blur_passes_budget" in rules

    (hypr_dir / "glass.conf").write_text(
        "# decoration:blur:size = 12\n"
        "decoration:blur:size = 6\n"
        "decoration:blur:passes = 2\n"
        "decoration:blur:xray = true\n",
        encoding="utf-8",
    )
    rc_ok, data_ok = _run_checker(tmp_path, scope="auto")
    assert rc_ok == 0, f"Valid colon-syntax Hyprland blur failed: {data_ok}"


def test_hardened_python_ast_indirect_vars_fstrings_and_methods(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "kite-bridge").mkdir(parents=True)
    (tmp_path / "kite-bridge" / "sneaky.py").write_text(
        "import os\n"
        'DXVK_VER = "1.10.3"\n'
        'OSX = "-cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel"\n'
        'WD = "persist.waydroid.multi_windows"\n'
        "def configure():\n"
        '    drv = "".join(["ir", "is"])\n'
        '    os.environ.setdefault("MESA_LOADER_DRIVER_OVERRIDE", drv)\n'
        '    va = f"i{\'HD\'}"\n'
        "    os.putenv(\"LIBVA_DRIVER_NAME\", va)\n"
        "    ver_minor = 3\n"
        '    os.environ.update([("DXVK_VER", f"2.{ver_minor}")])\n',
        encoding="utf-8",
    )
    rc, data = _run_checker(tmp_path, scope="auto")
    assert rc == 1
    rules = {v["rule"] for v in data["violations"]}
    assert {"no_iris", "no_ihd", "no_dxvk_2x"} <= rules


def test_hardened_cfg_scan_yaml_error_and_both_env_files(tmp_path: Path) -> None:
    _make_valid_m1_fixture(tmp_path)
    (tmp_path / "AGENTS.md").write_bytes((REPO_ROOT / "AGENTS.md").read_bytes())
    skill_dst = tmp_path / ".agents" / "skills" / "kite-os-builder" / "SKILL.md"
    skill_dst.parent.mkdir(parents=True)
    skill_dst.write_bytes((REPO_ROOT / ".agents" / "skills" / "kite-os-builder" / "SKILL.md").read_bytes())
    (tmp_path / "README.md").write_text("# KITE_OS\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='kite-os'\n", encoding="utf-8")

    # 1. Remove crocus from /etc/environment while keeping it in 10-kite-haswell.conf -> m1 must fail!
    (tmp_path / "iso-profile" / "airootfs" / "etc" / "environment").write_text(
        "LIBVA_DRIVER_NAME=i965\n", encoding="utf-8"
    )
    # 2. Inject active bad driver into grub.cfg + malformed YAML in workflows
    (tmp_path / "iso-profile" / "grub").mkdir(parents=True)
    (tmp_path / "iso-profile" / "grub" / "grub.cfg").write_text(
        "# LIBVA_DRIVER_NAME=iHD in comment is fine\n"
        "linux /arch/boot/x86_64/vmlinuz-linux-cachyos LIBVA_DRIVER_NAME=iHD MESA_LOADER_DRIVER_OVERRIDE=iris\n",
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows" / "bad.yml").write_text(
        "name: broken\njobs: [unclosed\n", encoding="utf-8"
    )

    rc, data = _run_checker(tmp_path, scope="m1")
    assert rc == 1
    rules = {v["rule"] for v in data["violations"]}
    assert "missing_crocus" in rules
    assert "no_ihd" in rules
    assert "no_iris" in rules
    assert "yaml_syntax" in rules
