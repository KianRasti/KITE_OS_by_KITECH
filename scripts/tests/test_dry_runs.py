from __future__ import annotations

import json
import subprocess
import sys

import pytest

from scripts.tests.m1_helpers import BASH_EXE, POWERSHELL_EXE, REPO_ROOT


def _run_bash(script_rel: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    script = REPO_ROOT / script_rel
    return subprocess.run(
        [BASH_EXE, str(script), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_ps1(script_rel: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    script = REPO_ROOT / script_rel
    return subprocess.run(
        [POWERSHELL_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_build_iso_sh_dry_run_json() -> None:
    res = _run_bash("scripts/build-iso.sh", ["--dry-run", "--json"])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["dry_run"] is True
    assert data["iso_path"].endswith("out/kite-os-folio9480-x86_64_v3.iso")
    assert data["sha256_path"].endswith("out/kite-os-folio9480-x86_64_v3.iso.sha256")
    assert data["stage_dest"].endswith("work/profile/airootfs/opt/kite-os-src/")
    assert data["command"][:3] == ["mkarchiso", "-v", "-w"]
    assert "NetworkManager.service" in data["systemd_wants"]
    assert "kite-firstboot-stage.service" in data["systemd_wants"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
@pytest.mark.parametrize("mode", ["Auto", "Docker", "WSL"])
def test_build_iso_ps1_dry_run_modes(mode: str) -> None:
    res = _run_ps1("scripts/build-iso.ps1", ["-Mode", mode, "-DryRun", "-Json"])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["dry_run"] is True
    assert data["requested_mode"] == mode
    assert data["target_iso"] == "out/kite-os-folio9480-x86_64_v3.iso"
    assert data["target_sha256"] == "out/kite-os-folio9480-x86_64_v3.iso.sha256"
    if mode == "Docker":
        assert "--privileged" in data["command"]
        assert "scripts/build-iso.sh" in data["command"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
def test_build_iso_ps1_live_nonexistent_wsl_distro_fails_cleanly() -> None:
    res = _run_ps1("scripts/build-iso.ps1", ["-Mode", "WSL", "-WslDistro", "__nonexistent_kite_distro__"])
    assert res.returncode != 0
    combined = res.stdout + "\n" + res.stderr
    assert "WSL2" in combined or "Docker" in combined


@pytest.mark.parametrize("ram", ["4G", "8G", "16G"])
@pytest.mark.parametrize("rotational", [0, 1])
def test_qemu_sh_dry_run_matrix(ram: str, rotational: int) -> None:
    res = _run_bash("scripts/test-qemu.sh", ["--dry-run", "--json", "--ram", ram, "--rotational", str(rotational)])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    argv = data["argv"]
    cmd = data["command"]
    assert "-cpu" in argv and "Haswell-noTSX" in argv
    assert "-smp" in argv and "4,cores=2,threads=2" in argv
    assert "-m" in argv and ram in argv
    assert any(a.startswith("if=pflash,format=raw,readonly=on,file=") for a in argv)
    assert "virtio-scsi-pci,id=scsi0" in argv
    expected_rate = "rotation_rate=1" if rotational == 0 else "rotation_rate=5400"
    assert any(expected_rate in a for a in argv)
    assert "user,id=net0" in argv
    assert "e1000e,netdev=net0" in argv
    assert "intel-hda" in argv and "hda-duplex" in argv
    assert data["accel"] in ("kvm", "whpx", "tcg")
    assert "out/kite-os-folio9480-x86_64_v3.iso" in cmd


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
@pytest.mark.parametrize("ram", ["4G", "8G", "16G"])
@pytest.mark.parametrize("rotational", [0, 1])
def test_qemu_ps1_dry_run_matrix(ram: str, rotational: int) -> None:
    res = _run_ps1("scripts/test-qemu.ps1", ["-DryRun", "-Json", "-Ram", ram, "-Rotational", str(rotational)])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    argv = data["argv"]
    assert "-cpu" in argv and "Haswell-noTSX" in argv
    assert "-smp" in argv and "4,cores=2,threads=2" in argv
    assert "-m" in argv and ram in argv
    assert any(a.startswith("if=pflash,format=raw,readonly=on,file=") for a in argv)
    assert "virtio-scsi-pci,id=scsi0" in argv
    expected_rate = "rotation_rate=1" if rotational == 0 else "rotation_rate=5400"
    assert any(expected_rate in a for a in argv)
    assert "e1000e,netdev=net0" in argv
    assert "intel-hda" in argv and "hda-duplex" in argv
    assert data["accel"] in ("kvm", "whpx", "tcg")
    assert "kite-os-folio9480-x86_64_v3.iso" in data["command"]


def test_qemu_sh_rejects_invalid_ram_and_rotational() -> None:
    res_ram = _run_bash("scripts/test-qemu.sh", ["--dry-run", "--ram", "32G"])
    assert res_ram.returncode != 0
    res_rot = _run_bash("scripts/test-qemu.sh", ["--dry-run", "--rotational", "2"])
    assert res_rot.returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
def test_qemu_ps1_rejects_invalid_ram_and_rotational() -> None:
    res_ram = _run_ps1("scripts/test-qemu.ps1", ["-DryRun", "-Ram", "32G"])
    assert res_ram.returncode != 0
    res_rot = _run_ps1("scripts/test-qemu.ps1", ["-DryRun", "-Rotational", "2"])
    assert res_rot.returncode != 0


def test_qemu_sh_disk_ssd_hdd_and_help() -> None:
    res_help = _run_bash("scripts/test-qemu.sh", ["--help"])
    assert res_help.returncode == 0
    for kw in ("4G", "8G", "16G", "ssd", "hdd"):
        assert kw.lower() in res_help.stdout.lower()

    res_ssd = _run_bash("scripts/test-qemu.sh", ["--dry-run", "--json", "--disk", "ssd"])
    res_hdd = _run_bash("scripts/test-qemu.sh", ["--dry-run", "--json", "--disk", "hdd"])
    assert res_ssd.returncode == 0 and res_hdd.returncode == 0
    assert json.loads(res_ssd.stdout)["rotation_rate"] == 1
    assert json.loads(res_hdd.stdout)["rotation_rate"] == 5400


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
def test_qemu_ps1_disk_ssd_hdd_and_help() -> None:
    res_help = _run_ps1("scripts/test-qemu.ps1", ["-Help"])
    assert res_help.returncode == 0
    for kw in ("4G", "8G", "16G", "ssd", "hdd"):
        assert kw.lower() in res_help.stdout.lower()

    res_ssd = _run_ps1("scripts/test-qemu.ps1", ["-DryRun", "-Json", "-Disk", "ssd"])
    res_hdd = _run_ps1("scripts/test-qemu.ps1", ["-DryRun", "-Json", "-Disk", "hdd"])
    assert res_ssd.returncode == 0 and res_hdd.returncode == 0
    assert json.loads(res_ssd.stdout)["rotation_rate"] == 1
    assert json.loads(res_hdd.stdout)["rotation_rate"] == 5400


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
def test_qemu_ps1_bare_disk_filename() -> None:
    for flag in ("-DiskPath", "-Disk"):
        res = _run_ps1("scripts/test-qemu.ps1", ["-DryRun", flag, "kite.qcow2", "-Json"])
        assert res.returncode == 0, res.stderr
        data = json.loads(res.stdout)
        assert data["disk"] == "kite.qcow2"
        assert data["ovmf_vars"] in (".\\OVMF_VARS.fd", "./OVMF_VARS.fd")
        assert "-cpu" in data["argv"] and "Haswell-noTSX" in data["argv"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 test")
def test_build_iso_ps1_docker_keyring_and_external_outdir() -> None:
    res = _run_ps1("scripts/build-iso.ps1", ["-Mode", "Docker", "-OutDir", r"C:\tmp\out", "-DryRun", "-Json"])
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert "pacman-key --init && pacman-key --populate archlinux" in data["command"]
    assert "C:\\tmp\\out:/kite-out" in data["command_args"]
    assert "--out-dir '/kite-out'" in data["command"]
    assert "C:/tmp/out" not in data["command"]
    assert data["target_iso"] == "/kite-out/kite-os-folio9480-x86_64_v3.iso"

    internal_out = str(REPO_ROOT / "custom-out")
    res_in = _run_ps1("scripts/build-iso.ps1", ["-Mode", "Docker", "-OutDir", internal_out, "-DryRun", "-Json"])
    assert res_in.returncode == 0, res_in.stderr
    data_in = json.loads(res_in.stdout)
    assert "--out-dir 'custom-out'" in data_in["command"]
    assert not any(arg.endswith(":/kite-out") for arg in data_in["command_args"])
