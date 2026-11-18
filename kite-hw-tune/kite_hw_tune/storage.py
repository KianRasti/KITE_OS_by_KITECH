"""Storage device discovery and rotational-aware I/O scheduler tuning."""

from __future__ import annotations

from kite_hw_tune.abstractions import SysFs
from kite_hw_tune.models import StorageDevice

SKIP_BLOCK_PREFIXES: tuple[str, ...] = (
    "loop",
    "ram",
    "zram",
    "sr",
    "dm-",
    "fd",
    "md",
    "nbd",
)


def parse_scheduler_list(raw: str) -> list[str]:
    """Parse /sys/block/<dev>/queue/scheduler contents into available names."""
    tokens: list[str] = []
    for part in raw.split():
        cleaned = part.strip("[]")
        if cleaned:
            tokens.append(cleaned)
    return tokens


def select_scheduler(rotational: int, available: list[str] | None) -> str:
    """Select optimal I/O scheduler based on rotational flag and available list."""
    if rotational == 0:
        if available is None:
            return "kyber"
        if not available:
            return "none"
        for candidate in ("kyber", "none", "mq-deadline"):
            if candidate in available:
                return candidate
        return available[0]

    if available is None:
        return "bfq"
    if not available:
        return "mq-deadline"
    for candidate in ("bfq", "mq-deadline", "kyber", "none"):
        if candidate in available:
            return candidate
    return available[0]


def detect_storage_devices(
    sys_fs: SysFs,
    *,
    warnings: list[str] | None = None,
) -> list[StorageDevice]:
    """Scan /sys/block/* for non-virtual block devices and determine target schedulers."""
    devices: list[StorageDevice] = []
    block_entries = sorted(sys_fs.list_dir("/sys/block"))

    for dev_name in block_entries:
        if dev_name.startswith(SKIP_BLOCK_PREFIXES):
            continue

        rot_path = f"/sys/block/{dev_name}/queue/rotational"
        rot_raw = sys_fs.read_text(rot_path)
        if rot_raw is None:
            if warnings is not None:
                warnings.append(f"Skipping block device {dev_name}: missing {rot_path}")
            continue

        rot_stripped = rot_raw.strip()
        if rot_stripped not in ("0", "1"):
            if warnings is not None:
                warnings.append(
                    f"Skipping block device {dev_name}: invalid rotational value {rot_stripped!r}"
                )
            continue
        rotational = int(rot_stripped)

        sched_path = f"/sys/block/{dev_name}/queue/scheduler"
        sched_raw = sys_fs.read_text(sched_path)
        available: list[str] | None
        if sched_raw is None:
            available = None
        else:
            available = parse_scheduler_list(sched_raw)
            if not available and warnings is not None:
                warnings.append(
                    f"Block device {dev_name} has empty scheduler list; defaulting safely"
                )

        chosen = select_scheduler(rotational, available)
        devices.append(
            StorageDevice(
                device=dev_name,
                rotational=rotational,
                scheduler=chosen,
            )
        )

    return devices


def apply_storage_schedulers(
    sys_fs: SysFs,
    *,
    apply: bool = True,
    warnings: list[str] | None = None,
) -> list[StorageDevice]:
    """Detect storage devices and optionally apply I/O schedulers via SysFs."""
    devices = detect_storage_devices(sys_fs, warnings=warnings)
    if not apply:
        return devices

    for dev in devices:
        sched_path = f"/sys/block/{dev.device}/queue/scheduler"
        sched_raw = sys_fs.read_text(sched_path)
        if sched_raw is not None and sched_raw.strip():
            ok = sys_fs.write_text(sched_path, dev.scheduler)
            if not ok and warnings is not None:
                warnings.append(
                    f"Failed to write scheduler {dev.scheduler!r} to {sched_path}"
                )

        if dev.rotational == 1 and dev.scheduler == "bfq":
            low_latency_path = f"/sys/block/{dev.device}/queue/iosched/low_latency"
            if sys_fs.exists(low_latency_path):
                sys_fs.write_text(low_latency_path, "1")

            read_ahead_path = f"/sys/block/{dev.device}/queue/read_ahead_kb"
            if sys_fs.exists(read_ahead_path):
                sys_fs.write_text(read_ahead_path, "256")

    return devices
