from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pytest

INSTALLER_DIR = Path(__file__).resolve().parents[1]
CALAMARES_DIR = INSTALLER_DIR / "calamares"
BRANDING_DIR = CALAMARES_DIR / "branding" / "kite-os"
MODULES_DIR = CALAMARES_DIR / "modules"
VALIDATION_DIR = INSTALLER_DIR / "validation"
INSTALL_SCRIPT = INSTALLER_DIR / "install.sh"
VALIDATE_SCRIPT = VALIDATION_DIR / "validate-hardware.sh"
CHECKLIST_FILE = VALIDATION_DIR / "folio9480m-checklist.md"


def to_bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt" and resolved.drive:
        drive = resolved.drive.rstrip(":").lower()
        rest = resolved.as_posix().split(":", 1)[1]
        return f"/{drive}{rest}"
    return resolved.as_posix()


def resolve_bash() -> str:
    if sys.platform == "win32":
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        if not git_bash.is_file():
            pytest.fail(f"Expected Git Bash at {git_bash}, but it was not found.")
        return str(git_bash)

    bash_bin = shutil.which("bash")
    if not bash_bin:
        pytest.skip("GNU bash not available on non-Windows host")
    probe = subprocess.run([bash_bin, "--version"], capture_output=True, text=True, check=False)
    if probe.returncode != 0 or "GNU bash" not in probe.stdout:
        pytest.skip("Genuine GNU bash required")
    return bash_bin


def run_bash_script(
    script: Path,
    args: list[str] | None = None,
    mock_bin: Path | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bash_exe = resolve_bash()
    script_posix = to_bash_path(script)
    argv = list(args or [])

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("KITE_MOCK_") and not k.startswith("KITE_CMD_")
    }
    env["MSYS2_ARG_CONV_EXCL"] = "*"
    if env_overrides:
        env.update(env_overrides)

    if mock_bin is not None:
        cmd = [
            bash_exe,
            "-c",
            'export PATH="$1:$PATH"; shift; exec "$@"',
            "_",
            to_bash_path(mock_bin),
            script_posix,
            *argv,
        ]
    else:
        cmd = [bash_exe, script_posix, *argv]

    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)


def _write_lf(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    if executable and os.name != "nt":
        path.chmod(0o755)


def make_mock_env(
    tmp_path: Path,
    *,
    ram_tier: str = "8G",
    rotational: int = 0,
    scheduler: str = "kyber",
    gl_driver: str = "crocus",
    va_driver: str = "i965",
    vulkan_driver: str = "anv",
    vulkan_version: str = "1.2.274",
    subvols: Iterable[str] = ("@", "@home", "@kitebridge", "@snapshots"),
    mount_opts: str = "rw,noatime,compress=zstd:1",
    has_ntsync: bool = True,
    has_binder: bool = True,
    has_kernel_params: bool = True,
    missing_kernel_param: str | None = None,
    services_active: bool = True,
    zram_algo_override: str | None = None,
    zram_bytes_override: int | None = None,
    missing_peripheral_modules: Iterable[str] = (),
) -> tuple[Path, Path]:
    mock_root = tmp_path / "mock_root"
    mock_bin = tmp_path / "mock_bin"
    mock_root.mkdir(parents=True, exist_ok=True)
    mock_bin.mkdir(parents=True, exist_ok=True)

    tier_specs = {
        "4G": {"ram_mb": 4096, "zram_pct": 150, "algo": "lz4", "swappiness": 180},
        "8G": {"ram_mb": 8192, "zram_pct": 100, "algo": "zstd", "swappiness": 150},
        "16G": {"ram_mb": 16384, "zram_pct": 50, "algo": "zstd", "swappiness": 100},
    }
    spec = tier_specs[ram_tier]
    mem_total_kb = spec["ram_mb"] * 1024
    zram_algo = zram_algo_override or spec["algo"]
    zram_bytes = (
        zram_bytes_override
        if zram_bytes_override is not None
        else spec["ram_mb"] * 1024 * 1024 * spec["zram_pct"] // 100
    )

    _write_lf(mock_root / "proc/meminfo", f"MemTotal:       {mem_total_kb} kB\nMemFree:        1048576 kB\n")
    _write_lf(mock_root / "proc/sys/vm/swappiness", f"{spec['swappiness']}\n")
    _write_lf(mock_root / "proc/sys/vm/page-cluster", "0\n")

    kparams = ["BOOT_IMAGE=/@/boot/vmlinuz-linux-cachyos", "quiet"]
    if has_kernel_params:
        for p in ("i915.enable_fbc=1", "i915.fastboot=1", "intel_pstate=active", "psi=1"):
            if p != missing_kernel_param:
                kparams.append(p)
    _write_lf(mock_root / "proc/cmdline", " ".join(kparams) + "\n")

    subvol_targets = {
        "@": "/",
        "@home": "/home",
        "@kitebridge": "/var/lib/kitebridge",
        "@snapshots": "/.snapshots",
    }
    mount_lines: list[str] = []
    findmnt_lines: list[str] = []
    btrfs_subvol_lines: list[str] = []
    for idx, sv in enumerate(subvols, start=256):
        tgt = subvol_targets[sv]
        opts = f"{mount_opts},subvol=/{sv}"
        mount_lines.append(f"/dev/sda2 {tgt} btrfs {opts} 0 0")
        findmnt_lines.append(f"{tgt} btrfs {opts}")
        btrfs_subvol_lines.append(f"ID {idx} gen 42 top level 5 path {sv}")

    _write_lf(mock_root / "proc/mounts", "\n".join(mount_lines) + "\n")

    if has_ntsync:
        _write_lf(mock_root / "dev/ntsync", "")
    if has_binder:
        _write_lf(mock_root / "dev/binder", "")
        _write_lf(mock_root / "dev/hwbinder", "")

    _write_lf(mock_root / "sys/class/dmi/id/product_name", "HP EliteBook Folio 9480m\n")
    _write_lf(mock_root / "sys/block/sda/queue/rotational", f"{rotational}\n")
    sched_tokens = ["none", "mq-deadline", "kyber", "bfq"]
    if scheduler not in sched_tokens:
        sched_tokens.append(scheduler)
    sched_str = " ".join(f"[{t}]" if t == scheduler else t for t in sched_tokens)
    _write_lf(mock_root / "sys/block/sda/queue/scheduler", sched_str + "\n")

    _write_lf(mock_root / "sys/block/zram0/comp_algorithm", f"lzo [{zram_algo}]\n")
    _write_lf(mock_root / "sys/block/zram0/disksize", f"{zram_bytes}\n")

    env_gl = "crocus" if gl_driver == "crocus" else gl_driver
    env_va = "i965" if va_driver == "i965" else va_driver
    _write_lf(
        mock_root / "etc/environment.d/10-kite-haswell.conf",
        f"MESA_LOADER_DRIVER_OVERRIDE={env_gl}\nLIBVA_DRIVER_NAME={env_va}\n",
    )
    _write_lf(
        mock_root / "etc/environment",
        f"MESA_LOADER_DRIVER_OVERRIDE={env_gl}\nLIBVA_DRIVER_NAME={env_va}\n",
    )

    svc_state = "active" if services_active else "inactive"
    _write_lf(mock_root / "run/systemd/units/kite-hw-tune.service", f"{svc_state}\n")
    _write_lf(mock_root / "run/systemd/units/kite-power.service", f"{svc_state}\n")

    profile = {
        "schema_version": 1,
        "ram_mb": spec["ram_mb"],
        "memory": {"tier": ram_tier, "zram_percent": spec["zram_pct"], "zram_algo": zram_algo},
        "subsystems": {"wine": {"dxvk_version": "1.10.3", "ntsync": True}},
    }
    _write_lf(mock_root / "run/kite-os/hw-profile.json", json.dumps(profile, indent=2) + "\n")

    # Mock CLI tools in mock_bin
    _write_lf(
        mock_bin / "glxinfo",
        f"#!/usr/bin/env bash\necho 'OpenGL vendor string: Intel'\necho 'OpenGL renderer string: Mesa Intel(R) HD Graphics 4400 (HSW GT2)'\necho 'Driver: {gl_driver}'\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "vainfo",
        f"#!/usr/bin/env bash\necho 'libva info: Trying to open /usr/lib/dri/{va_driver}_drv_video.so'\necho 'vainfo: Driver version: {va_driver}'\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "vulkaninfo",
        f"#!/usr/bin/env bash\necho 'GPU0:'\necho '\tapiVersion = {vulkan_version}'\necho '\tdriverName = {vulkan_driver}'\necho '\tdeviceName = Intel(R) HD Graphics 4400 (HSW GT2)'\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "zramctl",
        f"#!/usr/bin/env bash\necho '/dev/zram0 {zram_algo} {zram_bytes}'\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "findmnt",
        "#!/usr/bin/env bash\ncat <<'OUT'\n" + "\n".join(findmnt_lines) + "\nOUT\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "btrfs",
        "#!/usr/bin/env bash\ncat <<'OUT'\n" + "\n".join(btrfs_subvol_lines) + "\nOUT\n",
        executable=True,
    )
    _write_lf(
        mock_bin / "systemctl",
        f"#!/usr/bin/env bash\necho '{svc_state}'\n[[ '{svc_state}' == 'active' ]]\n",
        executable=True,
    )

    missing_mods = set(missing_peripheral_modules)
    for mod in ("iwlwifi", "btusb", "e1000e", "snd_hda_intel", "psmouse"):
        if mod not in missing_mods:
            _write_lf(mock_root / f"sys/module/{mod}/initstate", "live\n")

    _write_lf(
        mock_root / "proc/bus/input/devices",
        'I: Bus=0011 Vendor=0002 Product=0007 Version=01b1\nN: Name="SynPS/2 Synaptics TouchPad"\n',
    )
    _write_lf(mock_root / "sys/bus/usb/devices/1-1.4/idVendor", "138a\n")
    _write_lf(mock_root / "sys/bus/usb/devices/1-1.4/idProduct", "003f\n")

    return mock_root, mock_bin
