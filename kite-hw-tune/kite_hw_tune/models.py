"""Typed data models and schema v1 serialization for kite-hw-tune."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RamTier = Literal["4G", "8G", "16G"]
PowerSource = Literal["AC", "Battery"]
ZramAlgo = Literal["lz4", "zstd"]
EppMode = Literal["balance_performance", "balance_power"]
BlurTier = Literal["static", "kawase_2pass", "kawase_1pass", "kawase_full"]


class HardwareDetectionError(RuntimeError):
    """Raised when required hardware telemetry cannot be parsed or detected."""


@dataclass(frozen=True)
class MemoryProfile:
    tier: RamTier
    zram_percent: int
    zram_size_mb: int
    zram_algo: ZramAlgo
    idle_budget_mb: int
    sysctl: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "zram_percent": self.zram_percent,
            "zram_size_mb": self.zram_size_mb,
            "zram_algo": self.zram_algo,
            "idle_budget_mb": self.idle_budget_mb,
            "sysctl": dict(self.sysctl),
        }


@dataclass(frozen=True)
class PowerProfile:
    source: PowerSource
    epp: EppMode
    snd_hda_intel_power_save: int
    iwlwifi_power_save: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "epp": self.epp,
            "snd_hda_intel_power_save": self.snd_hda_intel_power_save,
            "iwlwifi_power_save": self.iwlwifi_power_save,
        }


@dataclass(frozen=True)
class BlurProfile:
    tier: BlurTier
    enabled: bool
    size: int
    passes: int
    xray: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "enabled": self.enabled,
            "size": self.size,
            "passes": self.passes,
            "xray": self.xray,
        }


@dataclass(frozen=True)
class StorageDevice:
    device: str
    rotational: int
    scheduler: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "rotational": self.rotational,
            "scheduler": self.scheduler,
        }


@dataclass(frozen=True)
class WineSubsystem:
    dxvk_version: str = "1.10.3"
    ntsync: bool = True
    prewarm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dxvk_version": self.dxvk_version,
            "ntsync": self.ntsync,
            "prewarm": self.prewarm,
        }


@dataclass(frozen=True)
class WaydroidSubsystem:
    idle_policy: str
    teardown_after_sec: int | None
    prewarm: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "idle_policy": self.idle_policy,
            "teardown_after_sec": self.teardown_after_sec,
            "prewarm": self.prewarm,
        }


@dataclass(frozen=True)
class OsxKvmSubsystem:
    hugepages_on_demand: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "hugepages_on_demand": self.hugepages_on_demand,
        }


@dataclass(frozen=True)
class KiteAiSubsystem:
    socket_only: bool = True
    background_watch: bool = True
    default_tier0_only: bool = False
    max_input_tokens: int = 400
    io_scheduling_class: str = "idle"

    def to_dict(self) -> dict[str, Any]:
        return {
            "socket_only": self.socket_only,
            "background_watch": self.background_watch,
            "default_tier0_only": self.default_tier0_only,
            "max_input_tokens": self.max_input_tokens,
            "io_scheduling_class": self.io_scheduling_class,
        }


@dataclass(frozen=True)
class SubsystemsProfile:
    wine: WineSubsystem
    waydroid: WaydroidSubsystem
    osx_kvm: OsxKvmSubsystem
    kite_ai: KiteAiSubsystem = field(default_factory=KiteAiSubsystem)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wine": self.wine.to_dict(),
            "waydroid": self.waydroid.to_dict(),
            "osx_kvm": self.osx_kvm.to_dict(),
            "kite_ai": self.kite_ai.to_dict(),
        }


@dataclass(frozen=True)
class HardwareProfile:
    ram_mb: int
    memory: MemoryProfile
    power: PowerProfile
    blur: BlurProfile
    storage: list[StorageDevice]
    subsystems: SubsystemsProfile
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ram_mb": self.ram_mb,
            "memory": self.memory.to_dict(),
            "power": self.power.to_dict(),
            "blur": self.blur.to_dict(),
            "storage": [dev.to_dict() for dev in self.storage],
            "subsystems": self.subsystems.to_dict(),
        }


@dataclass(frozen=True)
class GlassSettings:
    battery_glass_autosimplify: bool = True
    blur_radius: int = 6
    corner_radius: int = 12


@dataclass(frozen=True)
class SystemPaths:
    proc_root: str = "/proc"
    sys_root: str = "/sys"
    output_profile: str = "/run/kite-os/hw-profile.json"
    runtime_conf: str = "~/.config/hypr/kite-glass-runtime.conf"
    settings_file: str = "~/.config/kite-os/settings.json"
    env_file: str = "/etc/environment.d/10-kite-haswell.conf"
    sysctl_runtime_file: str = "/run/sysctl.d/99-kite-hw-tune.conf"


@dataclass(frozen=True)
class CmdResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class TuneResult:
    profile: HardwareProfile
    warnings: list[str] = field(default_factory=list)
    commands_run: list[list[str]] = field(default_factory=list)
    written_files: list[str] = field(default_factory=list)
