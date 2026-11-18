"""macOS subsystem package (native mounts, .pkg, .app bundles, Darling, OSX-KVM)."""

from __future__ import annotations

from .bundle import AppBundleParser, is_macho_bytes
from .darling import DarlingExecResult, DarlingRunner
from .mounts import MacMountManager, detect_image_kind
from .osx_kvm import KvmPreflightResult, OsxKvmBridge, check_kvm_preflight
from .packages import PkgHandler
from .qmp import QmpLifecycleManager

__all__ = [
    "AppBundleParser",
    "DarlingExecResult",
    "DarlingRunner",
    "KvmPreflightResult",
    "MacMountManager",
    "OsxKvmBridge",
    "PkgHandler",
    "QmpLifecycleManager",
    "check_kvm_preflight",
    "detect_image_kind",
    "is_macho_bytes",
]
