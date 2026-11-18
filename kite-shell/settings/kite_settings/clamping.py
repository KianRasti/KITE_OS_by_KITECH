"""Hardware clamping engine for Intel HD 4400 (HP Folio 9480m 4G/8G/16G, AC/Battery)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from kite_settings.models import HwProfile, KiteSettings, parse_spring_curve
from kite_settings.presets import GLASS_PRESETS

MITIGATIONS_SECURITY_WARNING = (
    "WARNING: Disabling CPU speculative execution mitigations (mitigations=off) "
    "exposes this Haswell system to Spectre, Meltdown, MDS, and L1TF side-channel attacks. "
    "Only enable in trusted single-user workloads. Requires reboot to take kernel effect."
)


@dataclass(frozen=True)
class EffectiveGlassConfig:
    blur_enabled: bool
    blur_size: int
    blur_passes: int
    blur_xray: bool
    effective_tier: str
    clamp_reason: str
    clamped: bool
    active_opacity: float
    inactive_opacity: float
    rounding: int
    accent_color: str
    surface_tint: str
    specular_edge_brightness: float
    specular_alpha_hex: str
    animations_enabled: bool
    anim_duration_windows_ds: int
    anim_duration_workspaces_ds: int
    spring_curve_tuple: tuple[float, float, float, float]
    mitigations_cmdline_flag: str
    mitigations_warning: str | None
    requires_reboot: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["spring_curve_tuple"] = list(self.spring_curve_tuple)
        return data


def _resolve_surface_tint(theme_preset: str) -> str:
    preset = GLASS_PRESETS.get(theme_preset)
    return preset.surface_tint if preset is not None else "#0F172A"


def clamp_settings(settings: KiteSettings, hw: HwProfile) -> EffectiveGlassConfig:
    """Compute effective runtime Glass configuration without mutating user settings."""
    is_4g = hw.ram_mb < 6144 or hw.memory_tier == "4G"
    is_battery = hw.power_source == "Battery"

    # Strict hardware clamping precedence (Priorities 1-5)
    if is_4g:
        blur_enabled = False
        blur_size = 0
        blur_passes = 0
        blur_xray = False
        effective_tier = "static"
        clamp_reason = "4G_STATIC_FALLBACK"
        clamped = settings.blur_radius > 0
    elif settings.theme_preset == "Ultra-Light Flat" or settings.blur_radius <= 0:
        blur_enabled = False
        blur_size = 0
        blur_passes = 0
        blur_xray = False
        effective_tier = "flat"
        clamp_reason = "USER_GLASS_DISABLED"
        clamped = False
    elif is_battery and settings.battery_glass_autosimplify:
        blur_enabled = True
        blur_size = max(1, min(settings.blur_radius, 4))
        blur_passes = 1
        blur_xray = True
        effective_tier = "kawase_1pass"
        clamp_reason = "BATTERY_AUTOSIMPLIFY_1PASS"
        clamped = settings.blur_radius > 4
    elif is_battery and not settings.battery_glass_autosimplify:
        blur_enabled = True
        blur_size = max(1, min(settings.blur_radius, 6))
        blur_passes = 2
        blur_xray = True
        effective_tier = "kawase_2pass"
        clamp_reason = "HD4400_BATTERY_OVERRIDE_CAP" if settings.blur_radius > 6 else "NONE"
        clamped = settings.blur_radius > 6
    else:
        # 8G/16G + AC
        blur_enabled = True
        blur_size = max(1, min(settings.blur_radius, 6))
        blur_passes = 2
        blur_xray = True
        effective_tier = "kawase_full" if hw.memory_tier == "16G" else "kawase_2pass"
        clamp_reason = "HD4400_AC_CAP" if settings.blur_radius > 6 else "NONE"
        clamped = settings.blur_radius > 6

    if not blur_enabled and settings.theme_preset == "Ultra-Light Flat":
        active_opacity = 1.0
        inactive_opacity = 0.96
    else:
        active_opacity = round(min(1.0, max(0.75, settings.transparency + 0.20)), 2)
        inactive_opacity = round(min(0.98, max(0.70, settings.transparency + 0.13)), 2)

    specular_alpha_hex = f"{round(settings.specular_edge_brightness * 255):02X}"
    animations_enabled = settings.animation_speed > 0.0
    if animations_enabled:
        anim_windows = max(1, min(15, round(3.0 / settings.animation_speed)))
        anim_workspaces = max(1, min(15, round(4.0 / settings.animation_speed)))
    else:
        anim_windows = 1
        anim_workspaces = 1

    curve_tuple = parse_spring_curve(settings.spring_curve)
    mitigations_flag = "mitigations=off" if settings.mitigations_off_requested else "mitigations=auto"
    mitigations_warning = MITIGATIONS_SECURITY_WARNING if settings.mitigations_off_requested else None

    return EffectiveGlassConfig(
        blur_enabled=blur_enabled,
        blur_size=blur_size,
        blur_passes=blur_passes,
        blur_xray=blur_xray,
        effective_tier=effective_tier,
        clamp_reason=clamp_reason,
        clamped=clamped,
        active_opacity=active_opacity,
        inactive_opacity=inactive_opacity,
        rounding=settings.corner_radius,
        accent_color=settings.accent_color,
        surface_tint=_resolve_surface_tint(settings.theme_preset),
        specular_edge_brightness=settings.specular_edge_brightness,
        specular_alpha_hex=specular_alpha_hex,
        animations_enabled=animations_enabled,
        anim_duration_windows_ds=anim_windows,
        anim_duration_workspaces_ds=anim_workspaces,
        spring_curve_tuple=curve_tuple,
        mitigations_cmdline_flag=mitigations_flag,
        mitigations_warning=mitigations_warning,
        requires_reboot=settings.mitigations_off_requested,
    )
