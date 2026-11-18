"""Hardware profile reader implementing PROJECT.md Interface Contract #1."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from . import REQUIRED_DXVK_VERSION
from .abstractions import PosixSystemProbe, SystemProbe
from .models import DxvkVersionViolationError, HwProfile, PowerSource, RamTier

DEFAULT_HW_PROFILE_PATH = "/run/kite-os/hw-profile.json"


def build_tier_profile(
    tier: RamTier,
    *,
    ram_mb: int | None = None,
    power_source: PowerSource = "AC",
    fallback_used: bool = False,
    warnings: tuple[str, ...] = (),
) -> HwProfile:
    """Construct an HwProfile matching PROJECT.md Contract #1 tier defaults."""
    if tier == "4G":
        return HwProfile(
            schema_version=1,
            ram_mb=ram_mb or 4096,
            tier="4G",
            power_source=power_source,
            wine_dxvk_version=REQUIRED_DXVK_VERSION,
            wine_ntsync=True,
            wine_prewarm=False,
            waydroid_idle_policy="freeze_then_teardown",
            waydroid_teardown_after_sec=300,
            waydroid_prewarm=False,
            osx_kvm_hugepages_on_demand=False,
            fallback_used=fallback_used,
            warnings=warnings,
        )
    if tier == "16G":
        return HwProfile(
            schema_version=1,
            ram_mb=ram_mb or 16384,
            tier="16G",
            power_source=power_source,
            wine_dxvk_version=REQUIRED_DXVK_VERSION,
            wine_ntsync=True,
            wine_prewarm=True,
            waydroid_idle_policy="prewarmed",
            waydroid_teardown_after_sec=None,
            waydroid_prewarm=True,
            osx_kvm_hugepages_on_demand=True,
            fallback_used=fallback_used,
            warnings=warnings,
        )
    return HwProfile(
        schema_version=1,
        ram_mb=ram_mb or 8192,
        tier="8G",
        power_source=power_source,
        wine_dxvk_version=REQUIRED_DXVK_VERSION,
        wine_ntsync=True,
        wine_prewarm=False,
        waydroid_idle_policy="cgroup_freeze",
        waydroid_teardown_after_sec=None,
        waydroid_prewarm=False,
        osx_kvm_hugepages_on_demand=False,
        fallback_used=fallback_used,
        warnings=warnings,
    )


def tier_from_ram_mb(ram_mb: int | None) -> RamTier:
    if ram_mb is None:
        return "4G"
    if ram_mb < 6144:
        return "4G"
    if ram_mb <= 12288:
        return "8G"
    return "16G"


class JsonHwProfileReader:
    """Reads `/run/kite-os/hw-profile.json` with strict DXVK 1.10.3 check and safe fallback."""

    def __init__(
        self,
        probe: SystemProbe | None = None,
        *,
        env: Mapping[str, str] | None = None,
        default_path: str = DEFAULT_HW_PROFILE_PATH,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.env = env if env is not None else os.environ
        self.default_path = default_path

    def resolve_path(self, explicit_path: str | None = None) -> str:
        if explicit_path:
            return explicit_path
        return (
            self.env.get("KITE_HW_PROFILE_PATH")
            or self.env.get("KITE_HW_PROFILE")
            or self.default_path
        )

    def read(self, path: str | None = None) -> HwProfile:
        target = self.resolve_path(path)
        if not self.probe.exists(target):
            return self._fallback_from_meminfo(f"Hardware profile '{target}' not found; using safe fallback.")

        try:
            raw_text = self.probe.read_text(target)
            data = json.loads(raw_text)
        except (OSError, ValueError, TypeError) as exc:
            return self._fallback_from_meminfo(f"Failed to parse hardware profile '{target}': {exc}")

        if not isinstance(data, dict):
            return self._fallback_from_meminfo(f"Hardware profile '{target}' is not a JSON object.")

        return self._parse_schema_v1(data)

    def _fallback_from_meminfo(self, reason: str) -> HwProfile:
        mem_mb = self.probe.mem_total_mb()
        tier = tier_from_ram_mb(mem_mb)
        return build_tier_profile(
            tier,
            ram_mb=mem_mb or (4096 if tier == "4G" else 8192 if tier == "8G" else 16384),
            fallback_used=True,
            warnings=(reason,),
        )

    def _parse_schema_v1(self, data: dict[str, Any]) -> HwProfile:
        memory = data.get("memory") or {}
        power = data.get("power") or {}
        subsystems = data.get("subsystems") or {}
        wine = subsystems.get("wine") or {}
        waydroid = subsystems.get("waydroid") or {}
        osx_kvm = subsystems.get("osx_kvm") or {}

        dxvk_version = str(wine.get("dxvk_version", REQUIRED_DXVK_VERSION)).strip()
        if dxvk_version != REQUIRED_DXVK_VERSION:
            raise DxvkVersionViolationError(
                f"hw-profile.json specifies unsupported DXVK version '{dxvk_version}'; "
                f"Haswell Intel HD 4400 requires strictly '{REQUIRED_DXVK_VERSION}'."
            )

        ram_mb = int(data.get("ram_mb") or 8192)
        raw_tier = str(memory.get("tier") or tier_from_ram_mb(ram_mb))
        tier: RamTier = raw_tier if raw_tier in ("4G", "8G", "16G") else tier_from_ram_mb(ram_mb)
        defaults = build_tier_profile(tier, ram_mb=ram_mb)

        raw_power = str(power.get("source", "AC"))
        power_source: PowerSource = "Battery" if raw_power == "Battery" else "AC"

        idle_policy = str(waydroid.get("idle_policy", defaults.waydroid_idle_policy))
        teardown_after_sec = waydroid.get("teardown_after_sec", defaults.waydroid_teardown_after_sec)
        if teardown_after_sec is not None:
            teardown_after_sec = int(teardown_after_sec)

        return HwProfile(
            schema_version=int(data.get("schema_version", 1)),
            ram_mb=ram_mb,
            tier=tier,
            power_source=power_source,
            wine_dxvk_version=dxvk_version,
            wine_ntsync=bool(wine.get("ntsync", defaults.wine_ntsync)),
            wine_prewarm=bool(wine.get("prewarm", defaults.wine_prewarm)),
            waydroid_idle_policy=idle_policy,
            waydroid_teardown_after_sec=teardown_after_sec,
            waydroid_prewarm=bool(waydroid.get("prewarm", defaults.waydroid_prewarm)),
            osx_kvm_hugepages_on_demand=bool(
                osx_kvm.get("hugepages_on_demand", defaults.osx_kvm_hugepages_on_demand)
            ),
            fallback_used=False,
            warnings=(),
        )
