"""KITE_OS Settings controller and HP Folio 9480m hardware clamping engine."""

from kite_settings.clamping import EffectiveGlassConfig, clamp_settings
from kite_settings.hypr_gen import (
    reload_hyprland,
    render_hypr_glass_conf,
    write_hypr_glass_conf,
)
from kite_settings.models import (
    HwProfile,
    KiteSettings,
    SettingsValidationError,
    default_config_dir,
    load_hw_profile,
    load_settings,
    resolve_hw_profile_path,
    resolve_hypr_conf_path,
    resolve_settings_path,
    save_settings,
)
from kite_settings.presets import (
    GLASS_PRESETS,
    WALLPAPER_CATALOG,
    GlassPreset,
    apply_preset,
    list_presets,
    resolve_preset,
)

__version__ = "0.1.0"

__all__ = [
    "EffectiveGlassConfig",
    "GLASS_PRESETS",
    "GlassPreset",
    "HwProfile",
    "KiteSettings",
    "SettingsValidationError",
    "WALLPAPER_CATALOG",
    "__version__",
    "apply_preset",
    "clamp_settings",
    "default_config_dir",
    "list_presets",
    "load_hw_profile",
    "load_settings",
    "reload_hyprland",
    "render_hypr_glass_conf",
    "resolve_hw_profile_path",
    "resolve_hypr_conf_path",
    "resolve_preset",
    "resolve_settings_path",
    "save_settings",
    "write_hypr_glass_conf",
]
