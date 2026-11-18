"""Shared pytest fixtures and offline sysfs/procfs/command builders for kite-hw-tune."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from kite_hw_tune.abstractions import FakeClock, FakeEnvWriter  # noqa: E402
from kite_hw_tune.models import CmdResult, SystemPaths  # noqa: E402
from kite_hw_tune.tuner import HardwareTuner  # noqa: E402


class RecordingRunner:
    """CmdRunner test double recording exact argv invocations without patching."""

    DEFAULT_BINS = frozenset(
        {"zramctl", "mkswap", "swapon", "swapoff", "sysctl", "iw", "udevadm"}
    )

    def __init__(
        self,
        stubs: Mapping[tuple[str, ...], CmdResult] | None = None,
        *,
        available_bins: Iterable[str] | None = None,
    ) -> None:
        self.stubs: dict[tuple[str, ...], CmdResult] = dict(stubs or {})
        self.available_bins: set[str] = (
            set(available_bins) if available_bins is not None else set(self.DEFAULT_BINS)
        )
        self.history: list[tuple[str, ...]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> CmdResult:
        cmd_tuple = tuple(argv)
        self.history.append(cmd_tuple)
        return self.stubs.get(cmd_tuple, CmdResult(argv=cmd_tuple, returncode=0))

    def which(self, binary: str) -> str | None:
        if binary in self.available_bins:
            return f"/usr/bin/{binary}"
        return None


class MockSysfsBuilder:
    """Constructs realistic temporary proc/sys/run/etc/config trees under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.proc_root = root / "proc"
        self.sys_root = root / "sys"
        self.run_dir = root / "run" / "kite-os"
        self.etc_dir = root / "etc"
        self.home_dir = root / "home"
        self.config_dir = self.home_dir / ".config"

        for d in (
            self.proc_root,
            self.sys_root,
            self.run_dir,
            self.etc_dir,
            self.config_dir / "kite-os",
            self.config_dir / "hypr",
        ):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_lf(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def set_meminfo_kb(self, total_kb: int, *, raw: str | None = None) -> Path:
        content = raw if raw is not None else (
            f"MemTotal:       {total_kb} kB\n"
            f"MemFree:        {total_kb // 4} kB\n"
            f"Buffers:          131072 kB\n"
            f"Cached:           524288 kB\n"
            "SwapTotal:             0 kB\n"
        )
        return self._write_lf(self.proc_root / "meminfo", content)

    def add_block_device(
        self,
        name: str,
        *,
        rotational: str | None = "0",
        scheduler: str | None = "[mq-deadline] kyber bfq none\n",
        has_iosched: bool = False,
        read_ahead_kb: str | None = "128\n",
    ) -> Path:
        dev_dir = self.sys_root / "block" / name
        dev_dir.mkdir(parents=True, exist_ok=True)
        if rotational is not None:
            self._write_lf(dev_dir / "queue" / "rotational", rotational)
        if scheduler is not None:
            self._write_lf(dev_dir / "queue" / "scheduler", scheduler)
        if has_iosched:
            self._write_lf(dev_dir / "queue" / "iosched" / "low_latency", "0\n")
        if read_ahead_kb is not None:
            self._write_lf(dev_dir / "queue" / "read_ahead_kb", read_ahead_kb)
        return dev_dir

    def set_power_supply(
        self,
        *,
        mains_name: str | None = "AC",
        mains_online: str = "1",
        battery_name: str | None = "BAT0",
        battery_status: str = "Charging",
    ) -> None:
        ps_root = self.sys_root / "class" / "power_supply"
        ps_root.mkdir(parents=True, exist_ok=True)
        if mains_name is not None:
            self._write_lf(ps_root / mains_name / "type", "Mains\n")
            self._write_lf(ps_root / mains_name / "online", f"{mains_online}\n")
        if battery_name is not None:
            self._write_lf(ps_root / battery_name / "type", "Battery\n")
            self._write_lf(ps_root / battery_name / "status", f"{battery_status}\n")

    def add_cpu_epp(
        self,
        cpu_count: int = 4,
        *,
        initial: str = "balance_performance\n",
        available: str = "default performance balance_performance balance_power power\n",
    ) -> None:
        for idx in range(cpu_count):
            cpufreq = self.sys_root / "devices" / "system" / "cpu" / f"cpu{idx}" / "cpufreq"
            self._write_lf(cpufreq / "energy_performance_preference", initial)
            if available is not None:
                self._write_lf(cpufreq / "energy_performance_available_preferences", available)
        self._write_lf(
            self.sys_root / "devices" / "system" / "cpu" / "intel_pstate" / "no_turbo",
            "0\n",
        )

    def add_audio_and_wifi(
        self,
        *,
        wlan_iface: str = "wlan0",
        snd_power_save: str = "0\n",
        iwl_power_save: str = "0\n",
    ) -> None:
        self._write_lf(
            self.sys_root / "module" / "snd_hda_intel" / "parameters" / "power_save",
            snd_power_save,
        )
        self._write_lf(
            self.sys_root / "module" / "snd_hda_intel" / "parameters" / "power_save_controller",
            "N\n",
        )
        self._write_lf(
            self.sys_root / "module" / "iwlwifi" / "parameters" / "power_save",
            iwl_power_save,
        )
        (self.sys_root / "class" / "net" / wlan_iface / "wireless").mkdir(
            parents=True, exist_ok=True
        )

    def set_settings(self, payload: Mapping[str, Any] | str) -> Path:
        text = payload if isinstance(payload, str) else json.dumps(payload, indent=2) + "\n"
        return self._write_lf(self.config_dir / "kite-os" / "settings.json", text)

    def system_paths(self) -> SystemPaths:
        return SystemPaths(
            proc_root=str(self.proc_root),
            sys_root=str(self.sys_root),
            output_profile=str(self.run_dir / "hw-profile.json"),
            runtime_conf=str(self.config_dir / "hypr" / "kite-glass-runtime.conf"),
            settings_file=str(self.config_dir / "kite-os" / "settings.json"),
            env_file=str(self.etc_dir / "environment.d" / "10-kite-haswell.conf"),
            sysctl_runtime_file=str(self.run_dir / "sysctl.d" / "99-kite-hw-tune.conf"),
        )


@pytest.fixture
def mock_sysfs(tmp_path: Path) -> MockSysfsBuilder:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.add_block_device("sda", rotational="0", scheduler="[mq-deadline] kyber bfq none\n")
    builder.set_power_supply(mains_online="1", battery_status="Full")
    builder.add_cpu_epp(4)
    builder.add_audio_and_wifi()
    return builder


@pytest.fixture
def recording_runner() -> RecordingRunner:
    return RecordingRunner()


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_env_writer() -> FakeEnvWriter:
    return FakeEnvWriter()


def make_tuner(
    builder: MockSysfsBuilder,
    runner: RecordingRunner | None = None,
) -> HardwareTuner:
    from kite_hw_tune.abstractions import DirectoryProcFs, DirectorySysFs, RealEnvWriter

    return HardwareTuner(
        proc_fs=DirectoryProcFs(builder.proc_root),
        sys_fs=DirectorySysFs(builder.sys_root),
        cmd=runner or RecordingRunner(),
        env_writer=RealEnvWriter(),
        clock=FakeClock(),
        paths=builder.system_paths(),
    )
