"""Schema v1 models, validation, path resolution, and atomic persistence."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CUBIC_BEZIER_RE = re.compile(
    r"^cubic-bezier\(\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*"
    r"([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\)$"
)

CANONICAL_PRESET_NAMES = (
    "Aero Blue",
    "Frosted Obsidian",
    "Emerald Glass",
    "Sunset Mica",
    "Ultra-Light Flat",
)
VALID_THEME_PRESETS = (*CANONICAL_PRESET_NAMES, "Custom")
VALID_TASKBAR_ALIGNMENTS = ("center", "left")
VALID_MEMORY_TIERS = ("4G", "8G", "16G")
VALID_POWER_SOURCES = ("AC", "Battery")


class SettingsValidationError(ValueError):
    """Raised when settings.json content or individual fields fail schema v1 validation."""


def default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else (Path.home() / ".config")


def resolve_settings_path(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    env = os.environ.get("KITE_SETTINGS_PATH")
    return Path(env) if env else (default_config_dir() / "kite-os" / "settings.json")


def resolve_hw_profile_path(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    return Path(os.environ.get("KITE_HW_PROFILE_PATH", "/run/kite-os/hw-profile.json"))


def resolve_hypr_conf_path(override: str | Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    env = os.environ.get("KITE_HYPR_GLASS_CONF")
    return Path(env) if env else (default_config_dir() / "hypr" / "kite-glass-runtime.conf")


def _require_strict_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsValidationError(f"{name} must be an integer, got {value!r}")
    return value


def _require_strict_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingsValidationError(f"{name} must be a number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise SettingsValidationError(f"{name} must be finite, got {value!r}")
    return result


def _require_strict_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsValidationError(f"{name} must be a boolean, got {value!r}")
    return value


def parse_spring_curve(curve: str) -> tuple[float, float, float, float]:
    if not isinstance(curve, str):
        raise SettingsValidationError(f"spring_curve must be a string, got {curve!r}")
    match = CUBIC_BEZIER_RE.match(curve.strip())
    if not match:
        raise SettingsValidationError(
            f"spring_curve must match 'cubic-bezier(x1, y1, x2, y2)', got {curve!r}"
        )
    vals = tuple(float(group) for group in match.groups())
    for val in vals:
        if not math.isfinite(val):
            raise SettingsValidationError(f"spring_curve values must be finite: {curve!r}")
    x1, _, x2, _ = vals
    if not (0.0 <= x1 <= 1.0 and 0.0 <= x2 <= 1.0):
        raise SettingsValidationError(
            f"spring_curve x1 and x2 must be within [0.0, 1.0], got {curve!r}"
        )
    return vals  # type: ignore[return-value]


@dataclass(frozen=True)
class KiteSettings:
    """User configuration persisted at ~/.config/kite-os/settings.json (schema v1)."""

    schema_version: int = 1
    theme_preset: str = "Aero Blue"
    accent_color: str = "#38BDF8"
    taskbar_alignment: str = "center"
    transparency: float = 0.72
    blur_radius: int = 6
    specular_edge_brightness: float = 0.35
    corner_radius: int = 12
    animation_speed: float = 1.0
    spring_curve: str = "cubic-bezier(0.22, 1.0, 0.36, 1.0)"
    wallpaper: str = "aero-glass-wave"
    battery_glass_autosimplify: bool = True
    mitigations_off_requested: bool = False

    def __post_init__(self) -> None:
        sv = _require_strict_int(self.schema_version, "schema_version")
        if sv != 1:
            raise SettingsValidationError(f"schema_version must equal 1, got {sv}")

        if not isinstance(self.theme_preset, str) or self.theme_preset not in VALID_THEME_PRESETS:
            raise SettingsValidationError(
                f"theme_preset must be one of {VALID_THEME_PRESETS}, got {self.theme_preset!r}"
            )

        if not isinstance(self.accent_color, str) or not HEX_COLOR_RE.match(self.accent_color):
            raise SettingsValidationError(
                f"accent_color must be a 6-digit hex string '#RRGGBB', got {self.accent_color!r}"
            )
        object.__setattr__(self, "accent_color", self.accent_color.upper())

        if self.taskbar_alignment not in VALID_TASKBAR_ALIGNMENTS:
            raise SettingsValidationError(
                f"taskbar_alignment must be 'center' or 'left', got {self.taskbar_alignment!r}"
            )

        trans = _require_strict_float(self.transparency, "transparency")
        if not (0.20 <= trans <= 1.00):
            raise SettingsValidationError(
                f"transparency must be within [0.20, 1.00], got {trans}"
            )
        object.__setattr__(self, "transparency", round(trans, 4))

        br = _require_strict_int(self.blur_radius, "blur_radius")
        if not (0 <= br <= 16):
            raise SettingsValidationError(f"blur_radius must be within [0, 16], got {br}")

        spec = _require_strict_float(self.specular_edge_brightness, "specular_edge_brightness")
        if not (0.00 <= spec <= 1.00):
            raise SettingsValidationError(
                f"specular_edge_brightness must be within [0.00, 1.00], got {spec}"
            )
        object.__setattr__(self, "specular_edge_brightness", round(spec, 4))

        cr = _require_strict_int(self.corner_radius, "corner_radius")
        if not (0 <= cr <= 24):
            raise SettingsValidationError(f"corner_radius must be within [0, 24], got {cr}")

        anim = _require_strict_float(self.animation_speed, "animation_speed")
        if not (0.0 <= anim <= 2.0):
            raise SettingsValidationError(
                f"animation_speed must be within [0.0, 2.0], got {anim}"
            )
        object.__setattr__(self, "animation_speed", round(anim, 4))

        parse_spring_curve(self.spring_curve)
        object.__setattr__(self, "spring_curve", self.spring_curve.strip())

        if not isinstance(self.wallpaper, str) or not self.wallpaper.strip():
            raise SettingsValidationError("wallpaper must be a non-empty string")
        object.__setattr__(self, "wallpaper", self.wallpaper.strip())

        _require_strict_bool(self.battery_glass_autosimplify, "battery_glass_autosimplify")
        _require_strict_bool(self.mitigations_off_requested, "mitigations_off_requested")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KiteSettings:
        if not isinstance(data, dict):
            raise SettingsValidationError("settings payload must be a JSON object")
        defaults = asdict(cls())
        merged = {**defaults}
        for key in defaults:
            if key in data:
                merged[key] = data[key]
        return cls(**merged)


@dataclass(frozen=True)
class HwProfile:
    """Hardware runtime profile read from /run/kite-os/hw-profile.json (schema v1)."""

    schema_version: int = 1
    ram_mb: int = 8192
    memory_tier: str = "8G"
    power_source: str = "AC"
    blur_tier: str = "kawase_2pass"
    blur_enabled: bool = True
    blur_size: int = 6
    blur_passes: int = 2
    blur_xray: bool = True
    storage: tuple[dict[str, Any], ...] = ()
    subsystems: dict[str, Any] = field(default_factory=dict)
    from_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ram_mb": self.ram_mb,
            "memory": {"tier": self.memory_tier},
            "power": {"source": self.power_source},
            "blur": {
                "tier": self.blur_tier,
                "enabled": self.blur_enabled,
                "size": self.blur_size,
                "passes": self.blur_passes,
                "xray": self.blur_xray,
            },
            "storage": list(self.storage),
            "subsystems": dict(self.subsystems),
            "from_fallback": self.from_fallback,
        }


def _infer_tier_from_ram(ram_mb: int) -> str:
    if ram_mb < 6144:
        return "4G"
    if ram_mb <= 12288:
        return "8G"
    return "16G"


def _normalize_power_source(raw: Any) -> str:
    if not isinstance(raw, str):
        return "AC"
    token = raw.strip().lower()
    if token in {"battery", "bat", "discharging", "dc"}:
        return "Battery"
    if token in {"ac", "mains", "charging", "full", "online"}:
        return "AC"
    return "AC"


def load_settings(path: str | Path | None = None) -> KiteSettings:
    target = resolve_settings_path(path)
    if not target.exists():
        return KiteSettings()
    try:
        raw = target.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SettingsValidationError(f"Failed to read settings at {target}: {exc}") from exc
    return KiteSettings.from_dict(payload)


def save_settings(settings: KiteSettings, path: str | Path | None = None) -> Path:
    validated = KiteSettings.from_dict(settings.to_dict())
    target = resolve_settings_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(validated.to_dict(), indent=2) + "\n"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=".settings-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = handle.name
            handle.write(serialized)
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return target


def _safe_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _safe_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _safe_nonempty_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return default


def load_hw_profile(path: str | Path | None = None) -> HwProfile:
    target = resolve_hw_profile_path(path)
    if not target.exists():
        return HwProfile(from_fallback=True)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return HwProfile(from_fallback=True)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return HwProfile(from_fallback=True)

    schema_version = _safe_int(payload.get("schema_version"), 1, minimum=1)
    ram_mb = _safe_int(payload.get("ram_mb"), 8192, minimum=1)

    mem = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    raw_tier = mem.get("tier")
    memory_tier = (
        raw_tier
        if isinstance(raw_tier, str) and raw_tier in VALID_MEMORY_TIERS
        else _infer_tier_from_ram(ram_mb)
    )

    pwr = payload.get("power") if isinstance(payload.get("power"), dict) else {}
    power_source = _normalize_power_source(pwr.get("source", "AC"))

    blur = payload.get("blur") if isinstance(payload.get("blur"), dict) else {}
    default_tier = (
        "static"
        if memory_tier == "4G"
        else (
            "kawase_1pass"
            if power_source == "Battery"
            else ("kawase_full" if memory_tier == "16G" else "kawase_2pass")
        )
    )
    default_enabled = memory_tier != "4G"
    default_size = 0 if memory_tier == "4G" else (4 if power_source == "Battery" else 6)
    default_passes = 0 if memory_tier == "4G" else (1 if power_source == "Battery" else 2)

    blur_tier = _safe_nonempty_str(blur.get("tier"), default_tier)
    blur_enabled = _safe_bool(blur.get("enabled"), default_enabled)
    blur_size = _safe_int(blur.get("size"), default_size, minimum=0)
    blur_passes = _safe_int(blur.get("passes"), default_passes, minimum=0)
    blur_xray = _safe_bool(blur.get("xray"), default_enabled)

    raw_storage = payload.get("storage", [])
    storage = tuple(item for item in raw_storage if isinstance(item, dict)) if isinstance(raw_storage, list) else ()
    raw_sub = payload.get("subsystems", {})
    subsystems = dict(raw_sub) if isinstance(raw_sub, dict) else {}

    return HwProfile(
        schema_version=schema_version,
        ram_mb=ram_mb,
        memory_tier=memory_tier,
        power_source=power_source,
        blur_tier=blur_tier,
        blur_enabled=blur_enabled,
        blur_size=blur_size,
        blur_passes=blur_passes,
        blur_xray=blur_xray,
        storage=storage,
        subsystems=subsystems,
        from_fallback=False,
    )
