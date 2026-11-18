"""Unit and contract tests for kite_settings (presets, clamping, Hyprland gen, CLI)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kite_settings import (
    GLASS_PRESETS,
    HwProfile,
    KiteSettings,
    SettingsValidationError,
    apply_preset,
    clamp_settings,
    load_hw_profile,
    load_settings,
    render_hypr_glass_conf,
    resolve_preset,
    save_settings,
)
from kite_settings.clamping import MITIGATIONS_SECURITY_WARNING
from kite_settings.cli import main as cli_main


def test_five_canonical_presets_conform_to_schema() -> None:
    expected_names = {
        "Aero Blue",
        "Frosted Obsidian",
        "Emerald Glass",
        "Sunset Mica",
        "Ultra-Light Flat",
    }
    assert set(GLASS_PRESETS.keys()) == expected_names

    base = KiteSettings(taskbar_alignment="left", battery_glass_autosimplify=False)
    for name in expected_names:
        updated = apply_preset(base, name)
        assert updated.theme_preset == name
        assert updated.taskbar_alignment == "left"
        assert updated.battery_glass_autosimplify is False
        assert updated.schema_version == 1

    assert resolve_preset("aero-blue").name == "Aero Blue"
    assert resolve_preset("ultra_light_flat").name == "Ultra-Light Flat"


def test_clamping_precedence_matrix() -> None:
    high_blur = KiteSettings(theme_preset="Custom", blur_radius=14, battery_glass_autosimplify=True)

    # Priority 1: 4G tier unconditionally disables blur
    for ram in (4096, 6143):
        for power in ("AC", "Battery"):
            hw_4g = HwProfile(ram_mb=ram, memory_tier="4G" if ram == 4096 else "8G", power_source=power)
            eff = clamp_settings(high_blur, hw_4g)
            assert eff.blur_enabled is False
            assert eff.blur_size == 0
            assert eff.blur_passes == 0
            assert eff.blur_xray is False
            assert eff.effective_tier == "static"
            assert eff.clamp_reason == "4G_STATIC_FALLBACK"

    # Priority 2: Ultra-Light Flat or blur_radius == 0 disables blur even on 16G AC
    hw_16g_ac = HwProfile(ram_mb=16384, memory_tier="16G", power_source="AC")
    flat_settings = apply_preset(KiteSettings(), "Ultra-Light Flat")
    eff_flat = clamp_settings(flat_settings, hw_16g_ac)
    assert eff_flat.blur_enabled is False
    assert eff_flat.blur_size == 0
    assert eff_flat.blur_passes == 0
    assert eff_flat.effective_tier == "flat"

    zero_blur = KiteSettings(theme_preset="Custom", blur_radius=0)
    assert clamp_settings(zero_blur, hw_16g_ac).effective_tier == "flat"

    # Priority 3: 8G/16G + Battery + battery_glass_autosimplify=True -> 1 pass, size <= 4
    hw_8g_bat = HwProfile(ram_mb=8192, memory_tier="8G", power_source="Battery")
    eff_bat_auto = clamp_settings(high_blur, hw_8g_bat)
    assert eff_bat_auto.blur_enabled is True
    assert eff_bat_auto.blur_size == 4
    assert eff_bat_auto.blur_passes == 1
    assert eff_bat_auto.blur_xray is True
    assert eff_bat_auto.effective_tier == "kawase_1pass"

    # Priority 4: 8G/16G + Battery + battery_glass_autosimplify=False -> 2 pass, size <= 6
    no_auto = KiteSettings(theme_preset="Custom", blur_radius=12, battery_glass_autosimplify=False)
    eff_bat_no_auto = clamp_settings(no_auto, hw_8g_bat)
    assert eff_bat_no_auto.blur_enabled is True
    assert eff_bat_no_auto.blur_size == 6
    assert eff_bat_no_auto.blur_passes == 2
    assert eff_bat_no_auto.effective_tier == "kawase_2pass"

    # Priority 5: 8G/16G + AC -> 2 pass, size <= 6
    hw_8g_ac = HwProfile(ram_mb=8192, memory_tier="8G", power_source="AC")
    eff_8g_ac = clamp_settings(high_blur, hw_8g_ac)
    assert eff_8g_ac.blur_enabled is True
    assert eff_8g_ac.blur_size == 6
    assert eff_8g_ac.blur_passes == 2
    assert eff_8g_ac.effective_tier == "kawase_2pass"

    eff_16g_ac = clamp_settings(high_blur, hw_16g_ac)
    assert eff_16g_ac.blur_size == 6
    assert eff_16g_ac.blur_passes == 2
    assert eff_16g_ac.effective_tier == "kawase_full"


def test_settings_json_roundtrip_and_validation_errors(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.json"
    # Missing file returns defaults
    assert load_settings(cfg) == KiteSettings()

    custom = KiteSettings(
        theme_preset="Emerald Glass",
        accent_color="#10b981",
        taskbar_alignment="left",
        transparency=0.70,
        blur_radius=10,
        specular_edge_brightness=0.40,
        corner_radius=14,
        animation_speed=1.25,
        spring_curve="cubic-bezier(0.16, 1.0, 0.3, 1.0)",
        wallpaper="emerald-aurora",
        battery_glass_autosimplify=False,
        mitigations_off_requested=True,
    )
    save_settings(custom, cfg)
    loaded = load_settings(cfg)
    assert loaded.accent_color == "#10B981"
    assert loaded.blur_radius == 10
    assert loaded.mitigations_off_requested is True

    # Invalid values raise SettingsValidationError
    with pytest.raises(SettingsValidationError):
        KiteSettings(transparency=0.10)
    with pytest.raises(SettingsValidationError):
        KiteSettings(blur_radius=20)
    with pytest.raises(SettingsValidationError):
        KiteSettings(corner_radius=30)
    with pytest.raises(SettingsValidationError):
        KiteSettings(taskbar_alignment="top")
    with pytest.raises(SettingsValidationError):
        KiteSettings(accent_color="blue")
    with pytest.raises(SettingsValidationError):
        KiteSettings(spring_curve="ease-in")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SettingsValidationError):
        load_settings(bad_json)


def test_hw_profile_fallback_and_tier_inference(tmp_path: Path) -> None:
    missing = tmp_path / "missing-hw.json"
    fb = load_hw_profile(missing)
    assert fb.from_fallback is True
    assert fb.memory_tier == "8G"
    assert fb.power_source == "AC"

    partial = tmp_path / "hw.json"
    partial.write_text(json.dumps({"ram_mb": 4096, "power": {"source": "discharging"}}), encoding="utf-8")
    parsed = load_hw_profile(partial)
    assert parsed.from_fallback is False
    assert parsed.memory_tier == "4G"
    assert parsed.power_source == "Battery"


def test_hypr_conf_generation_and_non_mutation_across_sync_cycles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings_path = tmp_path / "settings.json"
    hw_path = tmp_path / "hw-profile.json"
    hypr_path = tmp_path / "kite-glass-runtime.conf"

    hw_path.write_text(
        json.dumps({"schema_version": 1, "ram_mb": 8192, "memory": {"tier": "8G"}, "power": {"source": "AC"}}),
        encoding="utf-8",
    )

    rc = cli_main(
        [
            "--settings", str(settings_path),
            "--hw-profile", str(hw_path),
            "--hypr-conf", str(hypr_path),
            "--no-reload",
            "--json",
            "set",
            "--blur-radius", "12",
            "--mitigations-off", "true",
        ]
    )
    assert rc == 0
    out_ac = json.loads(capsys.readouterr().out)
    assert out_ac["settings"]["blur_radius"] == 12
    assert out_ac["effective"]["blur_size"] == 6
    assert out_ac["effective"]["blur_passes"] == 2
    assert len(out_ac["warnings"]) == 1
    conf_ac = hypr_path.read_text(encoding="utf-8")
    assert "size = 6" in conf_ac and "passes = 2" in conf_ac and "xray = true" in conf_ac

    # Switch to Battery -> user blur_radius=12 is preserved, runtime conf clamps to 1 pass size=4
    hw_path.write_text(
        json.dumps({"schema_version": 1, "ram_mb": 8192, "memory": {"tier": "8G"}, "power": {"source": "Battery"}}),
        encoding="utf-8",
    )
    rc = cli_main(
        [
            "--settings", str(settings_path),
            "--hw-profile", str(hw_path),
            "--hypr-conf", str(hypr_path),
            "--no-reload",
            "--json",
            "sync",
        ]
    )
    assert rc == 0
    out_bat = json.loads(capsys.readouterr().out)
    assert out_bat["settings"]["blur_radius"] == 12
    assert out_bat["effective"]["blur_size"] == 4
    assert out_bat["effective"]["blur_passes"] == 1
    conf_bat = hypr_path.read_text(encoding="utf-8")
    assert "size = 4" in conf_bat and "passes = 1" in conf_bat

    # Switch back to AC -> restores 2-pass size=6 automatically
    hw_path.write_text(
        json.dumps({"schema_version": 1, "ram_mb": 8192, "memory": {"tier": "8G"}, "power": {"source": "AC"}}),
        encoding="utf-8",
    )
    rc = cli_main(
        [
            "--settings", str(settings_path),
            "--hw-profile", str(hw_path),
            "--hypr-conf", str(hypr_path),
            "--no-reload",
            "--json",
            "sync",
        ]
    )
    assert rc == 0
    out_ac_again = json.loads(capsys.readouterr().out)
    assert out_ac_again["effective"]["blur_size"] == 6
    assert out_ac_again["effective"]["blur_passes"] == 2

    # Direct render check
    rendered = render_hypr_glass_conf(KiteSettings(), clamp_settings(KiteSettings(), HwProfile()), HwProfile())
    assert "decoration {" in rendered
    assert "blur {" in rendered
    assert "iris" not in rendered and "iHD" not in rendered


def test_hw_profile_malformed_field_types_fallback(tmp_path: Path) -> None:
    malformed_cases = [
        {"blur": {"size": "bad"}},
        {"schema_version": None},
        {"blur": {"passes": "bad"}},
        {"ram_mb": True},
        {"ram_mb": 8192.5},
        {"ram_mb": -100},
        {"blur": "not-a-dict", "memory": 42, "power": ["bad"]},
        {"blur": {"enabled": "false", "xray": 1, "tier": None, "size": True, "passes": 2.5}},
    ]
    for idx, payload in enumerate(malformed_cases):
        hw_path = tmp_path / f"bad_hw_{idx}.json"
        hw_path.write_text(json.dumps(payload), encoding="utf-8")
        prof = load_hw_profile(hw_path)
        assert prof.from_fallback is False
        assert prof.schema_version >= 1
        assert prof.ram_mb > 0
        assert prof.memory_tier in {"4G", "8G", "16G"}
        assert prof.power_source in {"AC", "Battery"}
        assert isinstance(prof.blur_enabled, bool)
        assert isinstance(prof.blur_xray, bool)
        assert isinstance(prof.blur_size, int) and not isinstance(prof.blur_size, bool)
        assert isinstance(prof.blur_passes, int) and not isinstance(prof.blur_passes, bool)
        assert isinstance(prof.blur_tier, str) and len(prof.blur_tier) > 0


def test_cli_mitigations_off_single_stderr_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings_path = tmp_path / "settings.json"
    hw_path = tmp_path / "hw-profile.json"
    hypr_path = tmp_path / "kite-glass-runtime.conf"
    hw_path.write_text(
        json.dumps({"schema_version": 1, "ram_mb": 8192, "memory": {"tier": "8G"}, "power": {"source": "AC"}}),
        encoding="utf-8",
    )

    rc = cli_main(
        [
            "--settings", str(settings_path),
            "--hw-profile", str(hw_path),
            "--hypr-conf", str(hypr_path),
            "--no-reload",
            "set",
            "--mitigations-off", "true",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err.count(MITIGATIONS_SECURITY_WARNING) == 1
    assert captured.err.count("WARNING:") == 1

    rc_ack = cli_main(
        [
            "--settings", str(settings_path),
            "--hw-profile", str(hw_path),
            "--hypr-conf", str(hypr_path),
            "--no-reload",
            "set",
            "--mitigations-off", "true",
            "--confirm-security-risk",
        ]
    )
    assert rc_ack == 0
    captured_ack = capsys.readouterr()
    assert captured_ack.err.count(MITIGATIONS_SECURITY_WARNING) == 1
    assert captured_ack.err.count("WARNING:") == 1
