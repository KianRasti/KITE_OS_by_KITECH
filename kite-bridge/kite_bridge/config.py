"""Configuration, Haswell environment pins, and path resolution for KiteBridge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Mapping

from . import LIBVA_DRIVER_PIN, MESA_DRIVER_PIN, REQUIRED_DXVK_VERSION
from .abstractions import PosixSystemProbe, SystemProbe
from .models import DxvkVersionViolationError

SYSTEM_DATA_DIR = "/var/lib/kitebridge"


def haswell_base_env() -> dict[str, str]:
    """Return mandatory Intel HD 4400 (Haswell GT2) driver pins per Contract #4."""
    return {
        "MESA_LOADER_DRIVER_OVERRIDE": MESA_DRIVER_PIN,
        "LIBVA_DRIVER_NAME": LIBVA_DRIVER_PIN,
    }


def validate_dxvk_version(version: str | None) -> str:
    """Enforce strict allowlist pin for DXVK 1.10.3."""
    if version is None or version.strip() == "":
        return REQUIRED_DXVK_VERSION
    normalized = version.strip().lstrip("vV")
    if normalized != REQUIRED_DXVK_VERSION:
        raise DxvkVersionViolationError(
            f"Unsupported DXVK version '{version}'. "
            f"Intel HD 4400 Vulkan 1.2 (anv) requires strictly DXVK '{REQUIRED_DXVK_VERSION}'."
        )
    return REQUIRED_DXVK_VERSION


def resolve_home_dir(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    home = source.get("KITEBRIDGE_HOME") or source.get("HOME")
    if home:
        return home.replace("\\", "/").rstrip("/") or "/"
    return os.path.expanduser("~").replace("\\", "/").rstrip("/") or "/home/kite"


def resolve_xdg_data_home(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    xdg = source.get("XDG_DATA_HOME")
    if xdg:
        return xdg.replace("\\", "/").rstrip("/")
    return f"{resolve_home_dir(source)}/.local/share"


def resolve_data_root(
    probe: SystemProbe | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve @kitebridge data root (Contract #5), falling back cleanly on dev/user hosts."""
    source = env if env is not None else os.environ
    override = source.get("KITEBRIDGE_DATA_DIR")
    if override:
        return override.replace("\\", "/").rstrip("/")
    if probe is not None and probe.exists(SYSTEM_DATA_DIR) and probe.access_rw(SYSTEM_DATA_DIR):
        return SYSTEM_DATA_DIR
    if probe is None and os.name != "nt":
        p = PosixSystemProbe()
        if p.exists(SYSTEM_DATA_DIR) and p.access_rw(SYSTEM_DATA_DIR):
            return SYSTEM_DATA_DIR
    return f"{resolve_xdg_data_home(source)}/kitebridge"


@dataclass(frozen=True)
class BridgeConfig:
    data_dir: str
    xdg_data_home: str
    home_dir: str
    hw_profile_path: str = "/run/kite-os/hw-profile.json"
    wine_prefix: str = ""
    wine_dxvk_dir: str = ""
    waydroid_prop_path: str = "/var/lib/waydroid/waydroid_base.prop"
    waydroid_overlay_dir: str = "/var/lib/waydroid/overlay"
    macos_dir: str = ""
    icons_dir: str = ""
    applications_dir: str = ""
    user_name: str = ""
    base_env: dict[str, str] = field(default_factory=haswell_base_env)

    @classmethod
    def from_env(
        cls,
        *,
        probe: SystemProbe | None = None,
        env: Mapping[str, str] | None = None,
        hw_profile_path: str | None = None,
    ) -> "BridgeConfig":
        source = env if env is not None else os.environ
        home_dir = resolve_home_dir(source)
        xdg_data_home = resolve_xdg_data_home(source)
        data_dir = resolve_data_root(probe=probe, env=source)
        wine_prefix = source.get("WINEPREFIX") or f"{data_dir}/wine/prefixes/default"
        user_name = source.get("USER") or (PurePosixPath(home_dir).name if source is not os.environ else "") or "kite"
        return cls(
            data_dir=data_dir,
            xdg_data_home=xdg_data_home,
            home_dir=home_dir,
            hw_profile_path=(
                hw_profile_path
                or source.get("KITE_HW_PROFILE_PATH")
                or source.get("KITE_HW_PROFILE")
                or "/run/kite-os/hw-profile.json"
            ),
            wine_prefix=wine_prefix.replace("\\", "/"),
            wine_dxvk_dir=f"{data_dir}/wine/dxvk/{REQUIRED_DXVK_VERSION}",
            waydroid_prop_path=source.get(
                "KITEBRIDGE_WAYDROID_PROP", "/var/lib/waydroid/waydroid_base.prop"
            ),
            waydroid_overlay_dir=source.get(
                "KITEBRIDGE_WAYDROID_OVERLAY", "/var/lib/waydroid/overlay"
            ),
            macos_dir=f"{data_dir}/macos",
            icons_dir=f"{data_dir}/icons",
            applications_dir=f"{xdg_data_home}/applications",
            user_name=user_name,
            base_env=haswell_base_env(),
        )

    def wine_prefix_path(self, name: str | None = None) -> str:
        if not name or name == "default":
            return self.wine_prefix
        return str(PurePosixPath(self.data_dir) / "wine" / "prefixes" / name)
