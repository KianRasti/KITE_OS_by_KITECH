"""Dynamic hardware auto-tuner for KITE_OS on HP EliteBook Folio 9480m."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kite_hw_tune.models import (
    BlurProfile,
    CmdResult,
    GlassSettings,
    HardwareDetectionError,
    HardwareProfile,
    MemoryProfile,
    OsxKvmSubsystem,
    PowerProfile,
    PowerSource,
    RamTier,
    StorageDevice,
    SubsystemsProfile,
    SystemPaths,
    TuneResult,
    WaydroidSubsystem,
    WineSubsystem,
)

if TYPE_CHECKING:
    from kite_hw_tune.tuner import HardwareTuner

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "BlurProfile",
    "CmdResult",
    "GlassSettings",
    "HardwareDetectionError",
    "HardwareProfile",
    "HardwareTuner",
    "MemoryProfile",
    "OsxKvmSubsystem",
    "PowerProfile",
    "PowerSource",
    "RamTier",
    "StorageDevice",
    "SubsystemsProfile",
    "SystemPaths",
    "TuneResult",
    "WaydroidSubsystem",
    "WineSubsystem",
]


def __getattr__(name: str) -> Any:
    if name == "HardwareTuner":
        from kite_hw_tune.tuner import HardwareTuner

        return HardwareTuner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
