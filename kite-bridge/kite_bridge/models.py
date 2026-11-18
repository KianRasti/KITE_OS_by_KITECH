"""Shared data models, enums, and domain exceptions for KiteBridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

RamTier = Literal["4G", "8G", "16G"]
PowerSource = Literal["AC", "Battery"]
DetectionMethod = Literal["extension", "magic", "magic+extension", "bundle"]


class BridgeError(RuntimeError):
    """Base error for all KiteBridge runtime operations."""


class DxvkVersionViolationError(BridgeError):
    """Raised when DXVK configuration deviates from pinned 1.10.3."""


class Vkd3dForbiddenError(BridgeError):
    """Raised when forbidden DX12 translation variables or DLLs are present."""


class RuntimeNotFoundError(BridgeError):
    """Raised when a required subsystem runtime binary is not available."""


class MissingToolError(BridgeError):
    """Raised when an external helper tool (e.g. darling-dmg, xar) is missing."""

    def __init__(self, tool: str, hint: str = "") -> None:
        self.tool = tool
        self.hint = hint
        msg = f"Required tool '{tool}' was not found on PATH."
        if hint:
            msg = f"{msg} {hint}"
        super().__init__(msg)


class KvmUnavailableError(BridgeError):
    """Raised when /dev/kvm is missing or inaccessible for OSX-KVM."""


class InvalidAppBundleError(BridgeError):
    """Raised when a macOS .app bundle is malformed or missing Info.plist."""


class QmpError(BridgeError):
    """Raised on QEMU Machine Protocol communication or command errors."""


class Platform(str, Enum):
    WIN = "win"
    ANDROID = "android"
    MACOS = "macos"
    UNKNOWN = "unknown"


class WaydroidState(str, Enum):
    STOPPED = "stopped"
    ACTIVE = "active"
    FROZEN = "frozen"


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class HwProfile:
    schema_version: int = 1
    ram_mb: int = 8192
    tier: RamTier = "8G"
    power_source: PowerSource = "AC"
    wine_dxvk_version: str = "1.10.3"
    wine_ntsync: bool = True
    wine_prewarm: bool = False
    waydroid_idle_policy: str = "cgroup_freeze"
    waydroid_teardown_after_sec: int | None = None
    waydroid_prewarm: bool = False
    osx_kvm_hugepages_on_demand: bool = False
    fallback_used: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteDecision:
    path: str
    extension: str
    platform: Platform
    handler: str
    mime_type: str
    detection_method: DetectionMethod
    dxvk_version: str | None
    wined3d_dx12: bool
    command: list[str]
    env: dict[str, str]
    tier_mode: RamTier = "8G"
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_inspect_dict(self) -> dict[str, Any]:
        """Serialize to PROJECT.md Interface Contract #7 schema."""
        return {
            "path": self.path,
            "extension": self.extension,
            "platform": self.platform.value,
            "handler": self.handler,
            "dxvk_version": self.dxvk_version,
            "wined3d_dx12": self.wined3d_dx12,
            "command": list(self.command),
            "env": dict(self.env),
            "mime_type": self.mime_type,
            "detection_method": self.detection_method,
            "tier_mode": self.tier_mode,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DesktopEntrySpec:
    slug: str
    app_name: str
    platform: Platform
    platform_tag: str
    handler: str
    source_path: str
    exec_command: str
    icon: str
    mime_types: tuple[str, ...] = ()
    desktop_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "app_name": self.app_name,
            "platform": self.platform.value,
            "platform_tag": self.platform_tag,
            "handler": self.handler,
            "source_path": self.source_path,
            "exec_command": self.exec_command,
            "icon": self.icon,
            "mime_types": list(self.mime_types),
            "desktop_path": self.desktop_path,
        }


@dataclass(frozen=True)
class IconExtractionResult:
    icon_value: str
    extracted: bool
    format: str
    source_path: str


@dataclass(frozen=True)
class WizardPlan:
    app_name: str
    platform: Platform
    platform_tag: str
    handler: str
    source_path: str
    target_prefix: str
    desktop_entry_path: str
    icon_path: str
    dxvk_version: str | None
    steps: list[str]
    env: dict[str, str]
    mode: Literal["qml", "cli", "dry-run"] = "cli"

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_name": self.app_name,
            "platform": self.platform.value,
            "platform_tag": self.platform_tag,
            "handler": self.handler,
            "source_path": self.source_path,
            "target_prefix": self.target_prefix,
            "desktop_entry_path": self.desktop_entry_path,
            "icon_path": self.icon_path,
            "dxvk_version": self.dxvk_version,
            "steps": list(self.steps),
            "env": dict(self.env),
            "mode": self.mode,
        }


@dataclass(frozen=True)
class MountRecord:
    source_path: str
    mountpoint: str
    fs_type: str
    read_only: bool = True
    fuse: bool = True


@dataclass(frozen=True)
class AppBundleInfo:
    bundle_path: str
    bundle_name: str
    bundle_identifier: str | None
    executable_name: str
    executable_path: str
    icon_path: str | None
    version: str | None
    min_macos: str | None
    tier: Literal["darling", "osx_kvm"]
    is_gui: bool
    is_binary_plist: bool = False


@dataclass(frozen=True)
class PkgInspectResult:
    pkg_path: str
    package_format: str
    identifier: str | None
    version: str | None
    title: str | None
    apps_found: list[str] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)
    extracted_to: str | None = None


@dataclass(frozen=True)
class QemuLaunchSpec:
    qemu_argv: list[str]
    virtiofsd_argv: list[str]
    bridge_argv: list[str]
    qmp_socket: str
    virtiofs_socket: str
    hugepages_enabled: bool
    vm_ram_mb: int
    resume_tag: str | None
    warnings: list[str] = field(default_factory=list)
