"""Tests for AC/Battery power tuning, Hyprland blur clamping, and Schema v1 validation."""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from kite_hw_tune.abstractions import FakeEnvWriter, FakeSysFs
from kite_hw_tune.power import build_blur_profile, detect_power_source, load_glass_settings
from tests.conftest import MockSysfsBuilder, RecordingRunner, make_tuner

HW_PROFILE_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "ram_mb",
        "memory",
        "power",
        "blur",
        "storage",
        "subsystems",
    ],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "ram_mb": {"type": "integer", "minimum": 1},
        "memory": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "tier",
                "zram_percent",
                "zram_size_mb",
                "zram_algo",
                "idle_budget_mb",
                "sysctl",
            ],
            "properties": {
                "tier": {"type": "string", "enum": ["4G", "8G", "16G"]},
                "zram_percent": {"type": "integer", "enum": [50, 100, 150]},
                "zram_size_mb": {"type": "integer", "minimum": 1},
                "zram_algo": {"type": "string", "enum": ["lz4", "zstd"]},
                "idle_budget_mb": {"type": "integer", "minimum": 1},
                "sysctl": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                },
            },
        },
        "power": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "source",
                "epp",
                "snd_hda_intel_power_save",
                "iwlwifi_power_save",
            ],
            "properties": {
                "source": {"type": "string", "enum": ["AC", "Battery"]},
                "epp": {
                    "type": "string",
                    "enum": ["balance_performance", "balance_power"],
                },
                "snd_hda_intel_power_save": {"type": "integer", "enum": [0, 1]},
                "iwlwifi_power_save": {"type": "boolean"},
            },
        },
        "blur": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tier", "enabled", "size", "passes", "xray"],
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": ["static", "kawase_2pass", "kawase_1pass", "kawase_full"],
                },
                "enabled": {"type": "boolean"},
                "size": {"type": "integer", "minimum": 0, "maximum": 6},
                "passes": {"type": "integer", "minimum": 0, "maximum": 2},
                "xray": {"type": "boolean"},
            },
        },
        "storage": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["device", "rotational", "scheduler"],
                "properties": {
                    "device": {"type": "string", "minLength": 1},
                    "rotational": {"type": "integer", "enum": [0, 1]},
                    "scheduler": {"type": "string", "minLength": 1},
                },
            },
        },
        "subsystems": {
            "type": "object",
            "additionalProperties": False,
            "required": ["wine", "waydroid", "osx_kvm"],
            "properties": {
                "wine": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["dxvk_version", "ntsync", "prewarm"],
                    "properties": {
                        "dxvk_version": {"type": "string", "const": "1.10.3"},
                        "ntsync": {"type": "boolean", "const": True},
                        "prewarm": {"type": "boolean"},
                    },
                },
                "waydroid": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["idle_policy", "teardown_after_sec", "prewarm"],
                    "properties": {
                        "idle_policy": {
                            "type": "string",
                            "enum": [
                                "freeze_then_teardown",
                                "cgroup_freeze",
                                "prewarmed",
                            ],
                        },
                        "teardown_after_sec": {"type": ["integer", "null"]},
                        "prewarm": {"type": "boolean"},
                    },
                },
                "osx_kvm": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["hugepages_on_demand"],
                    "properties": {
                        "hugepages_on_demand": {"type": "boolean"},
                    },
                },
                "kite_ai": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "socket_only",
                        "background_watch",
                        "default_tier0_only",
                        "max_input_tokens",
                        "io_scheduling_class",
                    ],
                    "properties": {
                        "socket_only": {"type": "boolean", "const": True},
                        "background_watch": {"type": "boolean"},
                        "default_tier0_only": {"type": "boolean"},
                        "max_input_tokens": {"type": "integer", "maximum": 400},
                        "io_scheduling_class": {"type": "string", "const": "idle"},
                    },
                },
            },
        },
    },
}


def test_power_source_detection_variants() -> None:
    assert (
        detect_power_source(
            FakeSysFs(
                {
                    "/sys/class/power_supply/AC/type": "Mains\n",
                    "/sys/class/power_supply/AC/online": "1\n",
                }
            )
        )
        == "AC"
    )
    assert (
        detect_power_source(
            FakeSysFs(
                {
                    "/sys/class/power_supply/AC/type": "Mains\n",
                    "/sys/class/power_supply/AC/online": "0\n",
                }
            )
        )
        == "Battery"
    )
    assert (
        detect_power_source(
            FakeSysFs(
                {
                    "/sys/class/power_supply/BAT0/type": "Battery\n",
                    "/sys/class/power_supply/BAT0/status": "Discharging\n",
                }
            )
        )
        == "Battery"
    )
    assert (
        detect_power_source(
            FakeSysFs(
                {
                    "/sys/class/power_supply/BAT0/type": "Battery\n",
                    "/sys/class/power_supply/BAT0/status": "Charging\n",
                }
            )
        )
        == "AC"
    )
    assert detect_power_source(FakeSysFs({})) == "AC"


def test_power_knobs_apply_and_missing_epp_graceful(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.set_power_supply(mains_online="0", battery_status="Discharging")
    builder.add_cpu_epp(2, initial="balance_performance\n")
    builder.add_audio_and_wifi(wlan_iface="wlan0", snd_power_save="0\n", iwl_power_save="0\n")

    runner = RecordingRunner()
    tuner = make_tuner(builder, runner)
    res = tuner.run_power_tune(apply_system=True, write_files=True)

    assert res.profile.power.source == "Battery"
    assert res.profile.power.epp == "balance_power"
    assert res.profile.power.snd_hda_intel_power_save == 1
    assert res.profile.power.iwlwifi_power_save is True

    assert (
        builder.sys_root
        / "devices"
        / "system"
        / "cpu"
        / "cpu0"
        / "cpufreq"
        / "energy_performance_preference"
    ).read_text(encoding="utf-8") == "balance_power"
    assert (
        builder.sys_root / "module" / "snd_hda_intel" / "parameters" / "power_save"
    ).read_text(encoding="utf-8") == "1"
    assert (
        builder.sys_root / "module" / "iwlwifi" / "parameters" / "power_save"
    ).read_text(encoding="utf-8") == "1"
    assert ("iw", "dev", "wlan0", "set", "power_save", "on") in runner.history

    # Now verify Haswell non-HWP system without energy_performance_preference does not crash
    builder2 = MockSysfsBuilder(tmp_path / "non_hwp")
    builder2.set_meminfo_kb(8192 * 1024)
    builder2.set_power_supply(mains_online="1", battery_status="Full")
    builder2.add_audio_and_wifi(wlan_iface="wlp2s0", snd_power_save="1\n", iwl_power_save="1\n")

    runner2 = RecordingRunner()
    tuner2 = make_tuner(builder2, runner2)
    res2 = tuner2.run_power_tune(apply_system=True, write_files=True)
    assert res2.profile.power.source == "AC"
    assert ("iw", "dev", "wlp2s0", "set", "power_save", "off") in runner2.history
    assert (
        builder2.sys_root / "module" / "snd_hda_intel" / "parameters" / "power_save"
    ).read_text(encoding="utf-8") == "0"


@pytest.mark.parametrize(
    ("ram_mb", "power_source", "autosimplify", "expected_blur"),
    [
        (4096, "AC", False, {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False}),
        (4096, "AC", True, {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False}),
        (4096, "Battery", False, {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False}),
        (4096, "Battery", True, {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False}),
        (8192, "AC", False, {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True}),
        (8192, "AC", True, {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True}),
        (8192, "Battery", True, {"tier": "kawase_1pass", "enabled": True, "size": 4, "passes": 1, "xray": True}),
        (8192, "Battery", False, {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True}),
        (16384, "AC", False, {"tier": "kawase_full", "enabled": True, "size": 6, "passes": 2, "xray": True}),
        (16384, "AC", True, {"tier": "kawase_full", "enabled": True, "size": 6, "passes": 2, "xray": True}),
        (16384, "Battery", True, {"tier": "kawase_1pass", "enabled": True, "size": 4, "passes": 1, "xray": True}),
        (16384, "Battery", False, {"tier": "kawase_full", "enabled": True, "size": 6, "passes": 2, "xray": True}),
    ],
)
def test_blur_matrix_and_schema_v1(
    tmp_path: Path,
    ram_mb: int,
    power_source: str,
    autosimplify: bool,
    expected_blur: dict[str, object],
) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(ram_mb * 1024)
    builder.add_block_device("sda", rotational="0", scheduler="[mq-deadline] kyber\n")
    builder.set_power_supply(mains_online="1" if power_source == "AC" else "0")
    builder.set_settings({"battery_glass_autosimplify": autosimplify, "blur_radius": 6})

    tuner = make_tuner(builder)
    res = tuner.run_hw_tune(apply_system=True, write_files=True)
    payload = res.profile.to_dict()

    jsonschema.validate(instance=payload, schema=HW_PROFILE_SCHEMA_V1)
    assert payload["blur"] == expected_blur

    profile_raw = (builder.run_dir / "hw-profile.json").read_bytes()
    assert b"\r\n" not in profile_raw
    assert not profile_raw.startswith(b"\xef\xbb\xbf")

    runtime_conf_bytes = (
        builder.config_dir / "hypr" / "kite-glass-runtime.conf"
    ).read_bytes()
    assert b"\r\n" not in runtime_conf_bytes
    runtime_text = runtime_conf_bytes.decode("utf-8")
    assert f"enabled = {'true' if expected_blur['enabled'] else 'false'}" in runtime_text
    assert f"size = {expected_blur['size']}" in runtime_text
    assert f"passes = {expected_blur['passes']}" in runtime_text


def test_blur_radius_clamping_and_corrupt_settings_fallback(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.set_power_supply(mains_online="1")
    builder.set_settings({"blur_radius": 16, "battery_glass_autosimplify": True})

    tuner = make_tuner(builder)
    res = tuner.run_power_tune(apply_system=False, write_files=True)
    assert res.profile.blur.size == 6
    assert res.profile.blur.passes == 2

    # Corrupt settings.json falls back cleanly to defaults
    builder.set_settings("{not valid json")
    res_corrupt = tuner.run_power_tune(
        power_override="Battery", apply_system=False, write_files=True
    )
    assert res_corrupt.profile.blur.tier == "kawase_1pass"
    assert res_corrupt.profile.blur.size == 4
    assert res_corrupt.profile.blur.passes == 1
    assert res_corrupt.warnings


def test_non_utf8_settings_json_falls_back_to_defaults(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.set_power_supply(mains_online="1")
    (builder.config_dir / "kite-os" / "settings.json").write_bytes(b"\xff\xfe{}")

    tuner = make_tuner(builder)
    res = tuner.run_power_tune(power_override="AC", apply_system=False, write_files=True)
    assert res.profile.blur.tier == "kawase_2pass"
    assert res.profile.blur.size == 6
    assert res.profile.blur.passes == 2
    assert res.warnings
    runtime_text = (
        builder.config_dir / "hypr" / "kite-glass-runtime.conf"
    ).read_text(encoding="utf-8")
    assert "rounding = 12" in runtime_text
    assert "size = 6" in runtime_text
    assert "passes = 2" in runtime_text


@pytest.mark.parametrize(
    "raw_json",
    [
        '{"blur_radius": true, "corner_radius": false}',
        '{"blur_radius": false, "corner_radius": true}',
        '{"blur_radius": Infinity, "corner_radius": -Infinity}',
        '{"blur_radius": -Infinity, "corner_radius": Infinity}',
        '{"blur_radius": NaN, "corner_radius": NaN}',
        '{"blur_radius": "abc", "corner_radius": "xyz", "battery_glass_autosimplify": "false"}',
    ],
)
def test_settings_rejects_booleans_and_non_finite_floats(raw_json: str) -> None:
    writer = FakeEnvWriter({"~/.config/kite-os/settings.json": raw_json})
    warnings: list[str] = []
    settings = load_glass_settings(writer, warnings=warnings)

    assert settings.blur_radius == 6
    assert settings.corner_radius == 12
    assert settings.battery_glass_autosimplify is True
    assert warnings

    ac_blur = build_blur_profile("8G", "AC", settings)
    assert ac_blur.enabled is True
    assert ac_blur.size == 6
    assert ac_blur.passes == 2

    bat_blur = build_blur_profile("8G", "Battery", settings)
    assert bat_blur.enabled is True
    assert bat_blur.size == 4
    assert bat_blur.passes == 1
