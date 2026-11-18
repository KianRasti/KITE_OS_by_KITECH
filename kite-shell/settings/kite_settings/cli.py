"""Command-line interface for kite-settings (used by Quickshell Studio, kite-hw-tune, and tests)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from kite_settings.clamping import clamp_settings
from kite_settings.hypr_gen import (
    reload_hyprland,
    render_hypr_glass_conf,
    write_hypr_glass_conf,
)
from kite_settings.models import (
    KiteSettings,
    SettingsValidationError,
    load_hw_profile,
    load_settings,
    resolve_hw_profile_path,
    resolve_hypr_conf_path,
    resolve_settings_path,
    save_settings,
)
from kite_settings.presets import apply_preset, list_presets


def _parse_bool(raw: str) -> bool:
    token = raw.strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value (true/false), got {raw!r}")


def _build_state_payload(
    settings: KiteSettings,
    settings_path: Path,
    hw_profile_path: Path,
    hypr_conf_path: Path,
    reloaded: bool = False,
) -> dict[str, Any]:
    hw = load_hw_profile(hw_profile_path)
    effective = clamp_settings(settings, hw)
    warnings: list[str] = []
    if effective.mitigations_warning:
        warnings.append(effective.mitigations_warning)
    return {
        "settings": settings.to_dict(),
        "effective": effective.to_dict(),
        "hw_profile": hw.to_dict(),
        "paths": {
            "settings": str(settings_path),
            "hw_profile": str(hw_profile_path),
            "hypr_conf": str(hypr_conf_path),
        },
        "hypr_reloaded": reloaded,
        "warnings": warnings,
    }


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    s = payload["settings"]
    eff = payload["effective"]
    hw = payload["hw_profile"]
    print(f"Preset:       {s['theme_preset']} (accent {s['accent_color']})")
    print(f"Taskbar:      {s['taskbar_alignment']} | Wallpaper: {s['wallpaper']}")
    print(
        f"Hardware:     {hw['memory']['tier']} ({hw['ram_mb']} MB) | Power: {hw['power']['source']}"
    )
    print(
        f"Effective FX: tier={eff['effective_tier']} enabled={eff['blur_enabled']} "
        f"size={eff['blur_size']} passes={eff['blur_passes']} xray={eff['blur_xray']} "
        f"clamp={eff['clamp_reason']}"
    )
    for warn in payload.get("warnings", []):
        print(warn, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--settings", type=Path, default=argparse.SUPPRESS, help="Path to settings.json"
    )
    common.add_argument(
        "--hw-profile", type=Path, default=argparse.SUPPRESS, help="Path to hw-profile.json"
    )
    common.add_argument(
        "--hypr-conf",
        type=Path,
        default=argparse.SUPPRESS,
        help="Path to kite-glass-runtime.conf",
    )
    common.add_argument(
        "--no-reload", action="store_true", default=argparse.SUPPRESS, help="Skip hyprctl reload"
    )
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output"
    )

    parser = argparse.ArgumentParser(
        prog="kite-settings",
        parents=[common],
        description="KITE_OS Glass customization controller and hardware-clamped Hyprland generator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", parents=[common], help="Show active settings and clamped runtime FX")
    sub.add_parser("presets", parents=[common], help="List all 5 canonical Glass presets")

    p_preset = sub.add_parser("preset", parents=[common], help="Apply a Glass preset theme")
    p_preset.add_argument("name", help="Preset name or slug (e.g. 'Aero Blue' or 'frosted-obsidian')")

    p_set = sub.add_parser("set", parents=[common], help="Update settings fields and sync Hyprland")
    p_set.add_argument("--theme-preset", type=str, default=None)
    p_set.add_argument("--accent-color", type=str, default=None)
    p_set.add_argument("--taskbar-alignment", choices=["center", "left"], default=None)
    p_set.add_argument("--transparency", type=float, default=None)
    p_set.add_argument("--blur-radius", type=int, default=None)
    p_set.add_argument("--specular-edge-brightness", type=float, default=None)
    p_set.add_argument("--corner-radius", type=int, default=None)
    p_set.add_argument("--animation-speed", type=float, default=None)
    p_set.add_argument("--spring-curve", type=str, default=None)
    p_set.add_argument("--wallpaper", type=str, default=None)
    p_set.add_argument("--battery-autosimplify", type=_parse_bool, default=None)
    p_set.add_argument("--mitigations-off", type=_parse_bool, default=None)
    p_set.add_argument(
        "--confirm-security-risk",
        action="store_true",
        help="Optional non-blocking audit acknowledgment flag when requesting --mitigations-off true",
    )

    sub.add_parser("sync", parents=[common], help="Recompute clamp and rewrite kite-glass-runtime.conf")
    sub.add_parser("reset", parents=[common], help="Reset settings.json to Aero Blue defaults")
    sub.add_parser("validate", parents=[common], help="Validate settings.json against schema v1")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings_path = resolve_settings_path(getattr(args, "settings", None))
    hw_path = resolve_hw_profile_path(getattr(args, "hw_profile", None))
    hypr_path = resolve_hypr_conf_path(getattr(args, "hypr_conf", None))
    as_json = bool(getattr(args, "json", False))
    no_reload = bool(getattr(args, "no_reload", False))

    try:
        if args.command == "presets":
            presets_data = [p.to_dict() for p in list_presets()]
            if as_json:
                print(json.dumps({"presets": presets_data}, indent=2))
            else:
                for p in presets_data:
                    print(
                        f"- {p['name']} ({p['slug']}): accent={p['accent_color']} "
                        f"alpha={p['transparency']} blur={p['blur_radius']} wall={p['wallpaper']}"
                    )
            return 0

        if args.command == "validate":
            settings = load_settings(settings_path)
            payload = _build_state_payload(settings, settings_path, hw_path, hypr_path)
            payload["valid"] = True
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print(f"OK: {settings_path} is valid (schema_version={settings.schema_version}).")
            return 0

        if args.command == "show":
            settings = load_settings(settings_path)
            payload = _build_state_payload(settings, settings_path, hw_path, hypr_path)
            _emit(payload, as_json)
            return 0

        if args.command == "reset":
            settings = KiteSettings()
            save_settings(settings, settings_path)
            hw = load_hw_profile(hw_path)
            eff = clamp_settings(settings, hw)
            write_hypr_glass_conf(render_hypr_glass_conf(settings, eff, hw), hypr_path)
            reloaded = reload_hyprland(no_reload)
            _emit(_build_state_payload(settings, settings_path, hw_path, hypr_path, reloaded), as_json)
            return 0

        if args.command == "sync":
            settings = load_settings(settings_path)
            if not settings_path.exists():
                save_settings(settings, settings_path)
            hw = load_hw_profile(hw_path)
            eff = clamp_settings(settings, hw)
            write_hypr_glass_conf(render_hypr_glass_conf(settings, eff, hw), hypr_path)
            reloaded = reload_hyprland(no_reload)
            _emit(_build_state_payload(settings, settings_path, hw_path, hypr_path, reloaded), as_json)
            return 0

        if args.command == "preset":
            current = load_settings(settings_path)
            updated = apply_preset(current, args.name)
            save_settings(updated, settings_path)
            hw = load_hw_profile(hw_path)
            eff = clamp_settings(updated, hw)
            write_hypr_glass_conf(render_hypr_glass_conf(updated, eff, hw), hypr_path)
            reloaded = reload_hyprland(no_reload)
            _emit(_build_state_payload(updated, settings_path, hw_path, hypr_path, reloaded), as_json)
            return 0

        if args.command == "set":
            current = load_settings(settings_path)
            updates: dict[str, Any] = {}
            visual_changed = False
            field_map = {
                "theme_preset": ("theme_preset", False),
                "accent_color": ("accent_color", True),
                "taskbar_alignment": ("taskbar_alignment", False),
                "transparency": ("transparency", True),
                "blur_radius": ("blur_radius", True),
                "specular_edge_brightness": ("specular_edge_brightness", True),
                "corner_radius": ("corner_radius", True),
                "animation_speed": ("animation_speed", True),
                "spring_curve": ("spring_curve", True),
                "wallpaper": ("wallpaper", True),
                "battery_autosimplify": ("battery_glass_autosimplify", False),
                "mitigations_off": ("mitigations_off_requested", False),
            }
            for arg_name, (field_name, is_visual) in field_map.items():
                val = getattr(args, arg_name)
                if val is not None:
                    updates[field_name] = val
                    if is_visual:
                        visual_changed = True
            if visual_changed and "theme_preset" not in updates:
                updates["theme_preset"] = "Custom"
            updated = replace(current, **updates)
            save_settings(updated, settings_path)
            hw = load_hw_profile(hw_path)
            eff = clamp_settings(updated, hw)
            write_hypr_glass_conf(render_hypr_glass_conf(updated, eff, hw), hypr_path)
            reloaded = reload_hyprland(no_reload)
            payload = _build_state_payload(updated, settings_path, hw_path, hypr_path, reloaded)
            _emit(payload, as_json)
            return 0

    except SettingsValidationError as exc:
        if as_json:
            print(json.dumps({"error": str(exc), "valid": False}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
