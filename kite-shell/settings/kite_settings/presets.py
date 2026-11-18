"""Canonical 5 Glass Preset Themes and dynamic wallpaper catalog for KITE_OS."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from kite_settings.models import KiteSettings, SettingsValidationError


@dataclass(frozen=True)
class GlassPreset:
    name: str
    slug: str
    accent_color: str
    transparency: float
    blur_radius: int
    specular_edge_brightness: float
    corner_radius: int
    animation_speed: float
    spring_curve: str
    wallpaper: str
    surface_tint: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


GLASS_PRESETS: dict[str, GlassPreset] = {
    "Aero Blue": GlassPreset(
        name="Aero Blue",
        slug="aero-blue",
        accent_color="#38BDF8",
        transparency=0.72,
        blur_radius=6,
        specular_edge_brightness=0.35,
        corner_radius=12,
        animation_speed=1.0,
        spring_curve="cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        wallpaper="aero-glass-wave",
        surface_tint="#0F172A",
        description="Windows 11-inspired cool sky-blue frosted acrylic (default).",
    ),
    "Frosted Obsidian": GlassPreset(
        name="Frosted Obsidian",
        slug="frosted-obsidian",
        accent_color="#818CF8",
        transparency=0.78,
        blur_radius=6,
        specular_edge_brightness=0.28,
        corner_radius=10,
        animation_speed=1.0,
        spring_curve="cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        wallpaper="obsidian-minimal-mesh",
        surface_tint="#090D16",
        description="Deep dark slate glass with indigo accents and subdued rim light.",
    ),
    "Emerald Glass": GlassPreset(
        name="Emerald Glass",
        slug="emerald-glass",
        accent_color="#10B981",
        transparency=0.70,
        blur_radius=6,
        specular_edge_brightness=0.40,
        corner_radius=14,
        animation_speed=1.0,
        spring_curve="cubic-bezier(0.16, 1.0, 0.3, 1.0)",
        wallpaper="emerald-aurora",
        surface_tint="#06201A",
        description="Luminous northern-lights emerald acrylic with high specular edge sheen.",
    ),
    "Sunset Mica": GlassPreset(
        name="Sunset Mica",
        slug="sunset-mica",
        accent_color="#FB923C",
        transparency=0.76,
        blur_radius=5,
        specular_edge_brightness=0.32,
        corner_radius=12,
        animation_speed=0.95,
        spring_curve="cubic-bezier(0.25, 1.0, 0.5, 1.0)",
        wallpaper="sunset-mica-horizon",
        surface_tint="#1F1218",
        description="Warm amber-dusk translucent mica surface tuned for low glare.",
    ),
    "Ultra-Light Flat": GlassPreset(
        name="Ultra-Light Flat",
        slug="ultra-light-flat",
        accent_color="#60A5FA",
        transparency=0.96,
        blur_radius=0,
        specular_edge_brightness=0.15,
        corner_radius=8,
        animation_speed=1.35,
        spring_curve="cubic-bezier(0.2, 0.0, 0.0, 1.0)",
        wallpaper="ultra-light-slate",
        surface_tint="#111827",
        description="Zero-blur fast matte surface maximizing battery life and 4 GB responsiveness.",
    ),
}

_PRESET_ALIASES: dict[str, str] = {}
for _name, _preset in GLASS_PRESETS.items():
    _PRESET_ALIASES[_name.lower()] = _name
    _PRESET_ALIASES[_preset.slug.lower()] = _name
    _PRESET_ALIASES[_preset.slug.replace("-", "_").lower()] = _name
    _PRESET_ALIASES[_name.replace(" ", "").replace("-", "").lower()] = _name


WALLPAPER_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "aero-glass-wave",
        "label": "Aero Glass Wave",
        "kind": "shader_gradient",
        "preset": "Aero Blue",
    },
    {
        "id": "obsidian-minimal-mesh",
        "label": "Obsidian Minimal Mesh",
        "kind": "shader_gradient",
        "preset": "Frosted Obsidian",
    },
    {
        "id": "emerald-aurora",
        "label": "Emerald Aurora",
        "kind": "shader_gradient",
        "preset": "Emerald Glass",
    },
    {
        "id": "sunset-mica-horizon",
        "label": "Sunset Mica Horizon",
        "kind": "shader_gradient",
        "preset": "Sunset Mica",
    },
    {
        "id": "ultra-light-slate",
        "label": "Ultra-Light Slate",
        "kind": "static",
        "preset": "Ultra-Light Flat",
    },
)


def resolve_preset(name_or_slug: str) -> GlassPreset:
    if not isinstance(name_or_slug, str) or not name_or_slug.strip():
        raise SettingsValidationError("Preset name must be a non-empty string")
    key = name_or_slug.strip().lower()
    canonical = _PRESET_ALIASES.get(key) or _PRESET_ALIASES.get(key.replace("_", "-"))
    if canonical is None:
        raise SettingsValidationError(
            f"Unknown preset {name_or_slug!r}. Expected one of: {list(GLASS_PRESETS.keys())}"
        )
    return GLASS_PRESETS[canonical]


def list_presets() -> list[GlassPreset]:
    return list(GLASS_PRESETS.values())


def apply_preset(settings: KiteSettings, preset_name: str) -> KiteSettings:
    """Apply a canonical preset's visual properties while preserving functional toggles."""
    preset = resolve_preset(preset_name)
    return replace(
        settings,
        theme_preset=preset.name,
        accent_color=preset.accent_color,
        transparency=preset.transparency,
        blur_radius=preset.blur_radius,
        specular_edge_brightness=preset.specular_edge_brightness,
        corner_radius=preset.corner_radius,
        animation_speed=preset.animation_speed,
        spring_curve=preset.spring_curve,
        wallpaper=preset.wallpaper,
    )
