"""AC/Battery power detection, CPU/audio/Wi-Fi tuning, and Hyprland blur clamping."""

from __future__ import annotations

import json
import math
import re

from kite_hw_tune.abstractions import CmdRunner, EnvWriter, SysFs
from kite_hw_tune.models import (
    BlurProfile,
    GlassSettings,
    PowerProfile,
    PowerSource,
    RamTier,
)

_CPU_DIR_RE = re.compile(r"^cpu\d+$")


def detect_power_source(sys_fs: SysFs) -> PowerSource:
    """Detect AC vs Battery from /sys/class/power_supply/*."""
    entries = sorted(sys_fs.list_dir("/sys/class/power_supply"))
    if not entries:
        return "AC"

    saw_offline_mains = False
    battery_discharging = False

    for entry in entries:
        base = f"/sys/class/power_supply/{entry}"
        psu_type = (sys_fs.read_text(f"{base}/type") or "").strip()
        if psu_type == "Mains":
            online = (sys_fs.read_text(f"{base}/online") or "").strip()
            if online == "1":
                return "AC"
            if online == "0":
                saw_offline_mains = True
        elif psu_type == "Battery":
            status = (sys_fs.read_text(f"{base}/status") or "").strip()
            if status == "Discharging":
                battery_discharging = True

    if saw_offline_mains:
        return "Battery"
    if battery_discharging:
        return "Battery"
    return "AC"


def build_power_profile(source: PowerSource) -> PowerProfile:
    """Build exact power settings for AC vs Battery."""
    if source == "AC":
        return PowerProfile(
            source="AC",
            epp="balance_performance",
            snd_hda_intel_power_save=0,
            iwlwifi_power_save=False,
        )
    return PowerProfile(
        source="Battery",
        epp="balance_power",
        snd_hda_intel_power_save=1,
        iwlwifi_power_save=True,
    )


def _parse_int_setting(
    raw_value: object,
    *,
    default: int,
    field_name: str,
    settings_path: str,
    warnings: list[str] | None,
) -> int:
    if isinstance(raw_value, bool):
        if warnings is not None:
            warnings.append(
                f"Invalid {field_name} in {settings_path}: boolean not allowed; "
                f"using default {default}"
            )
        return default
    if isinstance(raw_value, float) and not math.isfinite(raw_value):
        if warnings is not None:
            warnings.append(
                f"Invalid {field_name} in {settings_path}: non-finite float; "
                f"using default {default}"
            )
        return default
    if isinstance(raw_value, (int, float, str)):
        try:
            return int(raw_value)
        except (TypeError, ValueError, OverflowError):
            pass
    if warnings is not None:
        warnings.append(
            f"Invalid {field_name} in {settings_path}: {raw_value!r}; "
            f"using default {default}"
        )
    return default


def load_glass_settings(
    env_writer: EnvWriter,
    settings_path: str = "~/.config/kite-os/settings.json",
    *,
    warnings: list[str] | None = None,
) -> GlassSettings:
    """Read kite-settings JSON safely, falling back to defaults if missing or corrupt."""
    raw = env_writer.read_text(settings_path)
    if raw is None:
        if env_writer.exists(settings_path) and warnings is not None:
            warnings.append(
                f"Unreadable or non-UTF-8 settings in {settings_path}; using defaults"
            )
        return GlassSettings()

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        if warnings is not None:
            warnings.append(f"Invalid JSON in {settings_path}: {exc}; using defaults")
        return GlassSettings()

    if not isinstance(data, dict):
        if warnings is not None:
            warnings.append(f"Expected JSON object in {settings_path}; using defaults")
        return GlassSettings()

    autosimplify_raw = data.get("battery_glass_autosimplify", True)
    if isinstance(autosimplify_raw, bool):
        autosimplify = autosimplify_raw
    else:
        if warnings is not None:
            warnings.append(
                f"Invalid battery_glass_autosimplify in {settings_path}: "
                f"{autosimplify_raw!r}; using default True"
            )
        autosimplify = True

    blur_radius = _parse_int_setting(
        data.get("blur_radius", 6),
        default=6,
        field_name="blur_radius",
        settings_path=settings_path,
        warnings=warnings,
    )

    corner_radius = _parse_int_setting(
        data.get("corner_radius", 12),
        default=12,
        field_name="corner_radius",
        settings_path=settings_path,
        warnings=warnings,
    )
    corner_radius = max(0, min(corner_radius, 32))

    return GlassSettings(
        battery_glass_autosimplify=autosimplify,
        blur_radius=blur_radius,
        corner_radius=corner_radius,
    )


def build_blur_profile(
    tier: RamTier,
    source: PowerSource,
    settings: GlassSettings | None = None,
) -> BlurProfile:
    """Compute bounded Intel HD 4400 blur profile for tier x power x settings."""
    cfg = settings or GlassSettings()

    if tier == "4G":
        return BlurProfile(
            tier="static",
            enabled=False,
            size=0,
            passes=0,
            xray=False,
        )

    full_tier = "kawase_2pass" if tier == "8G" else "kawase_full"

    if source == "Battery" and cfg.battery_glass_autosimplify:
        clamped_size = min(max(cfg.blur_radius, 0), 4)
        if clamped_size <= 0:
            return BlurProfile(
                tier="kawase_1pass",
                enabled=False,
                size=0,
                passes=0,
                xray=False,
            )
        return BlurProfile(
            tier="kawase_1pass",
            enabled=True,
            size=clamped_size,
            passes=1,
            xray=True,
        )

    clamped_size = min(max(cfg.blur_radius, 0), 6)
    if clamped_size <= 0:
        return BlurProfile(
            tier=full_tier,  # type: ignore[arg-type]
            enabled=False,
            size=0,
            passes=0,
            xray=False,
        )
    return BlurProfile(
        tier=full_tier,  # type: ignore[arg-type]
        enabled=True,
        size=clamped_size,
        passes=2,
        xray=True,
    )


def render_hypr_runtime_conf(
    blur: BlurProfile,
    settings: GlassSettings | None = None,
    *,
    tier: RamTier = "8G",
    source: PowerSource = "AC",
) -> str:
    """Render Hyprland kite-glass-runtime.conf with bounded blur parameters."""
    cfg = settings or GlassSettings()
    enabled_str = "true" if blur.enabled else "false"
    xray_str = "true" if blur.xray else "false"
    safe_size = min(max(blur.size, 0), 6)
    safe_passes = min(max(blur.passes, 0), 2)

    return (
        f"# Auto-generated by kite-hw-tune (tier: {tier}, power: {source})\n"
        "# Do not edit manually; managed via kite-power and ~/.config/kite-os/settings.json\n"
        "decoration {\n"
        f"    rounding = {cfg.corner_radius}\n"
        "    blur {\n"
        f"        enabled = {enabled_str}\n"
        f"        size = {safe_size}\n"
        f"        passes = {safe_passes}\n"
        f"        xray = {xray_str}\n"
        "    }\n"
        "}\n"
    )


def _cpu_sort_key(name: str) -> tuple[int, str]:
    suffix = name[3:]
    return (int(suffix) if suffix.isdigit() else 0, name)


def apply_power_profile(
    sys_fs: SysFs,
    cmd: CmdRunner,
    profile: PowerProfile,
    *,
    apply: bool = True,
    warnings: list[str] | None = None,
) -> list[str]:
    """Apply CPU EPP, intel_pstate turbo, snd_hda_intel, and iwlwifi power saving."""
    out_warnings = warnings if warnings is not None else []
    if not apply:
        return out_warnings

    # 1. CPU EPP (gracefully optional on Haswell non-HWP systems)
    cpu_dirs = [
        name
        for name in sys_fs.list_dir("/sys/devices/system/cpu")
        if _CPU_DIR_RE.match(name)
    ]
    for cpu_name in sorted(cpu_dirs, key=_cpu_sort_key):
        epp_path = f"/sys/devices/system/cpu/{cpu_name}/cpufreq/energy_performance_preference"
        if not sys_fs.exists(epp_path):
            continue
        avail_path = (
            f"/sys/devices/system/cpu/{cpu_name}/cpufreq/"
            "energy_performance_available_preferences"
        )
        target_epp: str = profile.epp
        avail_raw = sys_fs.read_text(avail_path)
        if avail_raw is not None:
            avail_tokens = avail_raw.split()
            if avail_tokens and target_epp not in avail_tokens:
                fallback = "performance" if profile.source == "AC" else "powersave"
                if fallback in avail_tokens:
                    target_epp = fallback
        sys_fs.write_text(epp_path, target_epp)

    no_turbo_path = "/sys/devices/system/cpu/intel_pstate/no_turbo"
    if profile.source == "AC" and sys_fs.exists(no_turbo_path):
        sys_fs.write_text(no_turbo_path, "0")

    # 2. Audio power save (snd_hda_intel)
    audio_ps_path = "/sys/module/snd_hda_intel/parameters/power_save"
    if sys_fs.exists(audio_ps_path):
        sys_fs.write_text(audio_ps_path, str(profile.snd_hda_intel_power_save))

    audio_ctrl_path = "/sys/module/snd_hda_intel/parameters/power_save_controller"
    if sys_fs.exists(audio_ctrl_path):
        sys_fs.write_text(
            audio_ctrl_path,
            "Y" if profile.snd_hda_intel_power_save else "N",
        )

    # 3. Wi-Fi power save (sysfs parameter if writable in mocks + iw dev)
    iwl_ps_path = "/sys/module/iwlwifi/parameters/power_save"
    if sys_fs.exists(iwl_ps_path):
        sys_fs.write_text(iwl_ps_path, "1" if profile.iwlwifi_power_save else "0")

    net_ifaces = sorted(sys_fs.list_dir("/sys/class/net"))
    wireless_ifaces = [
        iface
        for iface in net_ifaces
        if sys_fs.exists(f"/sys/class/net/{iface}/wireless")
        or sys_fs.exists(f"/sys/class/net/{iface}/phy80211")
    ]
    if wireless_ifaces:
        if cmd.which("iw"):
            mode = "on" if profile.iwlwifi_power_save else "off"
            for iface in wireless_ifaces:
                res = cmd.run(["iw", "dev", iface, "set", "power_save", mode])
                if res.returncode != 0:
                    out_warnings.append(
                        f"iw dev {iface} set power_save {mode} exited {res.returncode}: "
                        f"{res.stderr.strip()}"
                    )
        else:
            out_warnings.append("iw binary not found; skipped wireless power_save toggle")

    return out_warnings


if __name__ == "__main__":
    import sys
    from kite_hw_tune.cli import main_power

    sys.exit(main_power())
