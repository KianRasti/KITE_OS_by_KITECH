"""Tests for `kite-hw-tune` and `kite-power` CLI flags, dry-run, and JSON output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from kite_hw_tune.cli import main_hw_tune, main_power
from tests.conftest import MockSysfsBuilder, PACKAGE_ROOT
from tests.test_power_and_glass import HW_PROFILE_SCHEMA_V1


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{PACKAGE_ROOT}{os.pathsep}{existing}" if existing else str(PACKAGE_ROOT)
    )
    return env


@pytest.mark.parametrize(
    ("module", "ram_mb", "power_arg", "expected_tier", "expected_power"),
    [
        ("kite_hw_tune", 4096, "battery", "4G", "Battery"),
        ("kite_hw_tune", 8192, "ac", "8G", "AC"),
        ("kite_hw_tune.power", 16384, "AC", "16G", "AC"),
    ],
)
def test_cli_subprocess_dry_run_json_pure_stdout(
    tmp_path: Path,
    module: str,
    ram_mb: int,
    power_arg: str,
    expected_tier: str,
    expected_power: str,
) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.add_block_device("sda", rotational="0", scheduler="[mq-deadline] kyber\n")
    out_profile = builder.run_dir / "hw-profile.json"
    runtime_conf = builder.config_dir / "hypr" / "kite-glass-runtime.conf"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            module,
            "--ram-mb",
            str(ram_mb),
            "--power",
            power_arg,
            "--proc-root",
            str(builder.proc_root),
            "--sys-root",
            str(builder.sys_root),
            "--output-profile",
            str(out_profile),
            "--runtime-conf",
            str(runtime_conf),
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    jsonschema.validate(instance=parsed, schema=HW_PROFILE_SCHEMA_V1)
    assert parsed["memory"]["tier"] == expected_tier
    assert parsed["power"]["source"] == expected_power
    assert not out_profile.exists()
    assert not runtime_conf.exists()


def test_cli_apply_with_no_cmds_writes_lf_files(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.add_block_device("sda", rotational="1", scheduler="[mq-deadline] bfq\n")
    builder.set_power_supply(mains_online="0")

    rc = main_hw_tune(
        [
            "apply",
            "--all",
            "--proc-root",
            str(builder.proc_root),
            "--sys-root",
            str(builder.sys_root),
            "--run-dir",
            str(builder.run_dir),
            "--config-dir",
            str(builder.config_dir),
            "--no-cmds",
            "--json",
        ]
    )
    assert rc == 0

    profile_path = builder.run_dir / "hw-profile.json"
    runtime_path = builder.config_dir / "hypr" / "kite-glass-runtime.conf"
    assert profile_path.exists()
    assert runtime_path.exists()

    profile_bytes = profile_path.read_bytes()
    runtime_bytes = runtime_path.read_bytes()
    assert b"\r\n" not in profile_bytes
    assert b"\r\n" not in runtime_bytes

    data = json.loads(profile_bytes.decode("utf-8"))
    jsonschema.validate(instance=data, schema=HW_PROFILE_SCHEMA_V1)
    assert data["storage"] == [{"device": "sda", "rotational": 1, "scheduler": "bfq"}]
    assert data["power"]["source"] == "Battery"
    assert data["blur"]["tier"] == "kawase_1pass"


def test_cli_power_entrypoint_with_apply_flag(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(16384 * 1024)
    builder.set_power_supply(mains_online="1")

    rc = main_power(
        [
            "--apply",
            "--proc-root",
            str(builder.proc_root),
            "--sys-root",
            str(builder.sys_root),
            "--run-dir",
            str(builder.run_dir),
            "--config-dir",
            str(builder.config_dir),
            "--no-cmds",
        ]
    )
    assert rc == 0
    assert (builder.run_dir / "hw-profile.json").exists()
    assert (builder.config_dir / "hypr" / "kite-glass-runtime.conf").exists()


@pytest.mark.parametrize(
    "bad_args",
    [
        ["--ram-mb", "0"],
        ["--ram-mb", "-512"],
        ["--power", "nuclear"],
    ],
)
def test_cli_negative_args_exit_nonzero(bad_args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_hw_tune([*bad_args, "--dry-run"])
    assert exc_info.value.code != 0


@pytest.mark.parametrize("module", ["kite_hw_tune", "kite_hw_tune.power"])
def test_cli_non_utf8_sysfs_and_settings_exit_zero_pure_json(
    tmp_path: Path, module: str
) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.set_power_supply(mains_online="1")
    builder.add_block_device("sda", rotational="0\n", scheduler="[mq-deadline] kyber\n")
    builder.add_block_device("sdl", rotational=None, scheduler="kyber\n")
    (builder.sys_root / "block" / "sdl" / "queue" / "rotational").write_bytes(
        b"\xff\xfe0\n"
    )
    (builder.config_dir / "kite-os" / "settings.json").write_bytes(b"\xff\xfe{}")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            module,
            "--proc-root",
            str(builder.proc_root),
            "--sys-root",
            str(builder.sys_root),
            "--run-dir",
            str(builder.run_dir),
            "--config-dir",
            str(builder.config_dir),
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "RuntimeWarning" not in proc.stderr
    assert "warning:" in proc.stderr
    parsed = json.loads(proc.stdout)
    jsonschema.validate(instance=parsed, schema=HW_PROFILE_SCHEMA_V1)
    assert [d["device"] for d in parsed["storage"]] == ["sda"]
    assert parsed["blur"]["size"] == 6


def test_cli_non_finite_and_bool_settings_apply_cleanly(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.set_power_supply(mains_online="1")
    builder.set_settings('{"blur_radius": Infinity, "corner_radius": false}')

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "kite_hw_tune.power",
            "--proc-root",
            str(builder.proc_root),
            "--sys-root",
            str(builder.sys_root),
            "--run-dir",
            str(builder.run_dir),
            "--config-dir",
            str(builder.config_dir),
            "--no-cmds",
            "--apply",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OverflowError" not in proc.stderr
    assert "RuntimeWarning" not in proc.stderr
    parsed = json.loads(proc.stdout)
    jsonschema.validate(instance=parsed, schema=HW_PROFILE_SCHEMA_V1)
    assert parsed["blur"]["size"] == 6
    assert parsed["blur"]["passes"] == 2
    runtime_text = (
        builder.config_dir / "hypr" / "kite-glass-runtime.conf"
    ).read_text(encoding="utf-8")
    assert "rounding = 12" in runtime_text
    assert "size = 6" in runtime_text
