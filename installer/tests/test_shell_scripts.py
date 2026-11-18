from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from conftest import INSTALL_SCRIPT, VALIDATE_SCRIPT, _write_lf, make_mock_env, resolve_bash, run_bash_script, to_bash_path


def test_bash_syntax_and_lf_endings():
    bash_exe = resolve_bash()
    for script in (INSTALL_SCRIPT, VALIDATE_SCRIPT):
        raw = script.read_bytes()
        assert b"\r\n" not in raw, f"{script.name} must use LF line endings"
        raw.decode("utf-8")
        proc = subprocess.run(
            [bash_exe, "-n", to_bash_path(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{script.name} failed bash -n: {proc.stderr}"
        assert proc.stderr == ""


def test_install_sh_staged_to_mock_root(tmp_path: Path):
    target_root = tmp_path / "staged_root"
    res = run_bash_script(INSTALL_SCRIPT, ["--root", to_bash_path(target_root)])
    assert res.returncode == 0, res.stderr

    assert (target_root / "etc/calamares/settings.conf").is_file()
    assert (target_root / "etc/calamares/modules/partition.conf").is_file()
    assert (target_root / "etc/calamares/modules/mount.conf").is_file()
    assert (target_root / "etc/calamares/modules/bootloader.conf").is_file()
    assert (target_root / "etc/calamares/modules/shellprocess.conf").is_file()
    assert (target_root / "etc/calamares/modules/shellprocess_cleanup.conf").is_file()
    assert (target_root / "etc/calamares/branding/kite-os/branding.desc").is_file()
    assert (target_root / "etc/calamares/branding/kite-os/stylesheet.qss").is_file()
    assert (target_root / "etc/calamares/branding/kite-os/show.qml").is_file()
    assert (target_root / "etc/calamares/branding/kite-os/assets/kite-logo.svg").is_file()
    assert (target_root / "usr/local/bin/kite-validate-hardware").is_file()
    assert (target_root / "usr/share/kite-os/validation/validate-hardware.sh").is_file()
    assert (target_root / "usr/share/kite-os/validation/folio9480m-checklist.md").is_file()


def test_install_sh_destdir_and_dry_run(tmp_path: Path):
    dry_root = tmp_path / "dry_root"
    dry_res = run_bash_script(INSTALL_SCRIPT, ["--root", to_bash_path(dry_root), "--dry-run"])
    assert dry_res.returncode == 0, dry_res.stderr
    assert "[DRY-RUN]" in dry_res.stdout
    assert not dry_root.exists()

    destdir_root = tmp_path / "destdir_root"
    dest_res = run_bash_script(
        INSTALL_SCRIPT,
        ["--skip-validation"],
        env_overrides={"DESTDIR": to_bash_path(destdir_root)},
    )
    assert dest_res.returncode == 0, dest_res.stderr
    assert (destdir_root / "etc/calamares/settings.conf").is_file()
    assert not (destdir_root / "usr/local/bin/kite-validate-hardware").exists()


@pytest.mark.parametrize(
    ("ram_tier", "rotational", "scheduler", "expected_algo"),
    [
        ("4G", 1, "bfq", "lz4"),
        ("8G", 0, "kyber", "zstd"),
        ("16G", 0, "none", "zstd"),
    ],
)
def test_validate_hardware_pass_tiers(
    tmp_path: Path,
    ram_tier: str,
    rotational: int,
    scheduler: str,
    expected_algo: str,
):
    mock_root, mock_bin = make_mock_env(
        tmp_path,
        ram_tier=ram_tier,
        rotational=rotational,
        scheduler=scheduler,
    )

    text_res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--mock-root", to_bash_path(mock_root), "--mock-bin", to_bash_path(mock_bin), "--strict"],
        mock_bin=mock_bin,
    )
    assert text_res.returncode == 0, text_res.stdout + text_res.stderr
    assert "[PASS] mesa_crocus" in text_res.stdout
    assert "[PASS] vaapi_i965" in text_res.stdout
    assert "[PASS] vulkan_anv" in text_res.stdout
    assert "[PASS] kernel_devices" in text_res.stdout
    assert "[PASS] btrfs_layout" in text_res.stdout
    assert "[PASS] zram_ram_tier" in text_res.stdout
    assert "[PASS] storage_schedulers" in text_res.stdout
    assert "[PASS] systemd_services" in text_res.stdout
    assert "[PASS] kernel_params" in text_res.stdout
    assert "[PASS] folio9480m_peripherals" in text_res.stdout

    json_res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert json_res.returncode == 0, json_res.stdout + json_res.stderr
    payload = json.loads(json_res.stdout)
    assert payload["schema_version"] == 1
    assert payload["ram_tier"] == ram_tier
    assert payload["summary"]["failed"] == 0
    assert payload["summary"]["passed"] == 10
    zram_check = next(c for c in payload["checks"] if c["id"] == "zram_ram_tier")
    assert expected_algo in zram_check["details"]


def test_validate_hardware_fail_wrong_gl_driver(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path, gl_driver="iris")
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    mesa = next(c for c in payload["checks"] if c["id"] == "mesa_crocus")
    assert mesa["status"] == "FAIL"
    assert "iris" in mesa["details"].lower()


def test_validate_hardware_fail_wrong_vaapi_driver(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path, va_driver="iHD")
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    va = next(c for c in payload["checks"] if c["id"] == "vaapi_i965")
    assert va["status"] == "FAIL"
    assert "ihd" in va["details"].lower()


def test_validate_hardware_fail_vulkan_exceeds_1_2(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path, vulkan_version="1.3.280")
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    vk = next(c for c in payload["checks"] if c["id"] == "vulkan_anv")
    assert vk["status"] == "FAIL"


def test_validate_hardware_fail_missing_subvolume(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path, subvols=("@", "@home", "@snapshots"))
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    btrfs = next(c for c in payload["checks"] if c["id"] == "btrfs_layout")
    assert btrfs["status"] == "FAIL"
    assert "@kitebridge" in btrfs["details"]


def test_validate_hardware_fail_missing_ntsync(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path, has_ntsync=False)
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    kdev = next(c for c in payload["checks"] if c["id"] == "kernel_devices")
    assert kdev["status"] == "FAIL"
    assert "ntsync" in kdev["details"]


def test_validate_hardware_fail_scheduler_mismatch(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path, rotational=0, scheduler="bfq")
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    sched = next(c for c in payload["checks"] if c["id"] == "storage_schedulers")
    assert sched["status"] == "FAIL"
    assert "bfq" in sched["details"]


def test_validate_hardware_fail_inactive_service_and_missing_kparam(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(
        tmp_path,
        services_active=False,
        missing_kernel_param="psi=1",
    )
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    svc = next(c for c in payload["checks"] if c["id"] == "systemd_services")
    kp = next(c for c in payload["checks"] if c["id"] == "kernel_params")
    assert svc["status"] == "FAIL"
    assert kp["status"] == "FAIL"
    assert "psi=1" in kp["details"]


def test_validate_hardware_fail_missing_peripheral_driver(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(
        tmp_path,
        missing_peripheral_modules=("iwlwifi", "e1000e"),
    )
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    periph = next(c for c in payload["checks"] if c["id"] == "folio9480m_peripherals")
    assert periph["status"] == "FAIL"
    assert "iwlwifi" in periph["details"]
    assert "e1000e" in periph["details"]


def test_validate_hardware_rejects_btrfs_compress_zstd_10(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(
        tmp_path,
        mount_opts="rw,noatime,compress=zstd:10",
    )
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    btrfs = next(c for c in payload["checks"] if c["id"] == "btrfs_layout")
    assert btrfs["status"] == "FAIL"
    assert "compress=zstd:1" in btrfs["details"]


def test_validate_hardware_rejects_vulkan_1_10_with_conformance_1_2(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path)
    _write_lf(
        mock_bin / "vulkaninfo",
        "#!/usr/bin/env bash\n"
        "echo 'GPU0:'\n"
        "echo '\tapiVersion = 1.10.0'\n"
        "echo '\tconformanceVersion = 1.2.7.1'\n"
        "echo '\tdriverName = anv'\n"
        "echo '\tdeviceName = Intel(R) HD Graphics 4400 (HSW GT2)'\n",
        executable=True,
    )
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    vk = next(c for c in payload["checks"] if c["id"] == "vulkan_anv")
    assert vk["status"] == "FAIL"
    assert "1.10.0" in vk["details"]


def test_validate_hardware_rejects_zram_lz4hc_on_4g(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(
        tmp_path,
        ram_tier="4G",
        rotational=1,
        scheduler="bfq",
        zram_algo_override="lz4hc",
    )
    _write_lf(
        mock_bin / "zramctl",
        "#!/usr/bin/env bash\necho '/dev/zram0 lz4hc 6144M'\n",
        executable=True,
    )
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    zram = next(c for c in payload["checks"] if c["id"] == "zram_ram_tier")
    assert zram["status"] == "FAIL"
    assert "lz4hc" in zram["details"]


def test_validate_hardware_rejects_iris_dri_and_ihd_drv_video(tmp_path: Path):
    mock_root, mock_bin = make_mock_env(tmp_path)
    _write_lf(
        mock_bin / "glxinfo",
        "#!/usr/bin/env bash\n"
        "echo 'OpenGL vendor string: Intel'\n"
        "echo 'Driver path: /usr/lib/dri/iris_dri.so'\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "vainfo",
        "#!/usr/bin/env bash\n"
        "echo 'libva info: Trying to open /usr/lib/dri/iHD_drv_video.so'\n",
        executable=True,
    )
    res = run_bash_script(
        VALIDATE_SCRIPT,
        ["--json", "--mock-root", to_bash_path(mock_root)],
        mock_bin=mock_bin,
    )
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    mesa = next(c for c in payload["checks"] if c["id"] == "mesa_crocus")
    va = next(c for c in payload["checks"] if c["id"] == "vaapi_i965")
    assert mesa["status"] == "FAIL"
    assert va["status"] == "FAIL"
