"""Command-line entrypoints for `kite-hw-tune` and `kite-power`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from kite_hw_tune.abstractions import (
    DirectoryProcFs,
    DirectorySysFs,
    LinuxCmdRunner,
    RealEnvWriter,
    SystemClock,
)
from kite_hw_tune.models import HardwareDetectionError, PowerSource, SystemPaths
from kite_hw_tune.tuner import HardwareTuner


def _parse_power(value: str) -> PowerSource:
    normalized = value.strip().lower()
    if normalized == "ac":
        return "AC"
    if normalized == "battery":
        return "Battery"
    raise argparse.ArgumentTypeError(
        f"Invalid --power value {value!r}; expected 'AC' or 'Battery'"
    )


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected integer, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"Expected positive integer, got {parsed}")
    return parsed


def build_parser(*, prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="KITE_OS dynamic hardware auto-tuner for HP EliteBook Folio 9480m",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("apply", "status"),
        default="apply",
        help="Action mode ('apply' default, or 'status' read-only inspection)",
    )
    parser.add_argument(
        "--ram-mb",
        type=_positive_int,
        default=None,
        help="Override detected RAM in MiB (must be > 0)",
    )
    parser.add_argument(
        "--power",
        type=_parse_power,
        default=None,
        help="Override detected power source (AC or Battery, case-insensitive)",
    )
    parser.add_argument(
        "--proc-root",
        default=os.environ.get("KITE_HW_TUNE_PROC_ROOT")
        or os.environ.get("KITE_PROC_ROOT")
        or "/proc",
        help="Root directory for procfs telemetry",
    )
    parser.add_argument(
        "--sys-root",
        default=os.environ.get("KITE_HW_TUNE_SYS_ROOT")
        or os.environ.get("KITE_SYS_ROOT")
        or "/sys",
        help="Root directory for sysfs telemetry",
    )
    parser.add_argument(
        "--run-dir",
        default=os.environ.get("KITE_HW_TUNE_RUN_DIR") or None,
        help="Override /run/kite-os directory for hw-profile.json",
    )
    parser.add_argument(
        "--output-profile",
        default=os.environ.get("KITE_HW_TUNE_OUTPUT_PROFILE") or None,
        help="Target path for Schema v1 hw-profile.json",
    )
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("KITE_HW_TUNE_CONFIG_DIR") or None,
        help="Override ~/.config base directory for settings.json and kite-glass-runtime.conf",
    )
    parser.add_argument(
        "--runtime-conf",
        default=os.environ.get("KITE_HW_TUNE_RUNTIME_CONF") or None,
        help="Target path for Hyprland kite-glass-runtime.conf",
    )
    parser.add_argument(
        "--settings-file",
        default=os.environ.get("KITE_HW_TUNE_SETTINGS_FILE") or None,
        help="Path to kite-settings settings.json",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("KITE_HW_TUNE_ENV_FILE")
        or "/etc/environment.d/10-kite-haswell.conf",
        help="Path to 10-kite-haswell.conf environment file",
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Also write 10-kite-haswell.conf driver environment pin file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate detection and output without writing files or running commands",
    )
    parser.add_argument(
        "--no-cmds",
        action="store_true",
        help="Write profile and runtime conf files without executing Linux commands or /sys writes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print Schema v1 hardware profile JSON to stdout",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Apply all subsystems (accepted for systemd ExecStart compatibility)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply profile (accepted for systemd ExecStart compatibility)",
    )
    return parser


def _resolve_paths(args: argparse.Namespace) -> SystemPaths:
    if args.output_profile:
        output_profile = args.output_profile
    elif args.run_dir:
        output_profile = str(Path(args.run_dir) / "hw-profile.json")
    else:
        output_profile = "/run/kite-os/hw-profile.json"

    if args.run_dir:
        sysctl_runtime_file = str(
            Path(args.run_dir) / "sysctl.d" / "99-kite-hw-tune.conf"
        )
    else:
        sysctl_runtime_file = "/run/sysctl.d/99-kite-hw-tune.conf"

    if args.runtime_conf:
        runtime_conf = args.runtime_conf
    elif args.config_dir:
        runtime_conf = str(Path(args.config_dir) / "hypr" / "kite-glass-runtime.conf")
    else:
        runtime_conf = "~/.config/hypr/kite-glass-runtime.conf"

    if args.settings_file:
        settings_file = args.settings_file
    elif args.config_dir:
        settings_file = str(Path(args.config_dir) / "kite-os" / "settings.json")
    else:
        settings_file = "~/.config/kite-os/settings.json"

    return SystemPaths(
        proc_root=args.proc_root,
        sys_root=args.sys_root,
        output_profile=output_profile,
        runtime_conf=runtime_conf,
        settings_file=settings_file,
        env_file=args.env_file,
        sysctl_runtime_file=sysctl_runtime_file,
    )


def _run_cli(argv: Sequence[str] | None, *, mode: str) -> int:
    prog = "kite-power" if mode == "power" else "kite-hw-tune"
    parser = build_parser(prog=prog)
    args = parser.parse_args(list(argv) if argv is not None else None)

    is_status = args.action == "status"
    dry_run = bool(args.dry_run or is_status)
    apply_system = not dry_run and not args.no_cmds
    write_files = not dry_run

    paths = _resolve_paths(args)
    tuner = HardwareTuner(
        proc_fs=DirectoryProcFs(Path(paths.proc_root)),
        sys_fs=DirectorySysFs(Path(paths.sys_root), dry_run=not apply_system),
        cmd=LinuxCmdRunner(dry_run=not apply_system),
        env_writer=RealEnvWriter(dry_run=not write_files),
        clock=SystemClock(),
        paths=paths,
    )

    try:
        if mode == "power":
            result = tuner.run_power_tune(
                ram_mb_override=args.ram_mb,
                power_override=args.power,
                apply_system=apply_system,
                write_files=write_files,
            )
        else:
            result = tuner.run_hw_tune(
                ram_mb_override=args.ram_mb,
                power_override=args.power,
                apply_system=apply_system,
                write_files=write_files,
                write_env_file=bool(args.write_env and write_files),
            )
    except (HardwareDetectionError, ValueError, OSError) as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return 1

    for warn in result.warnings:
        print(f"{prog}: warning: {warn}", file=sys.stderr)

    if args.json:
        print(json.dumps(result.profile.to_dict(), indent=2))
    else:
        print(
            f"{prog}: tier={result.profile.memory.tier} "
            f"ram_mb={result.profile.ram_mb} "
            f"power={result.profile.power.source} "
            f"blur={result.profile.blur.tier} "
            f"storage={len(result.profile.storage)}"
        )

    return 0


def main_hw_tune(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `kite-hw-tune`."""
    return _run_cli(argv, mode="hw-tune")


def main_power(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `kite-power`."""
    return _run_cli(argv, mode="power")
