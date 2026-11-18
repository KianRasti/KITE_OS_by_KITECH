"""macOS .app bundle parser (Info.plist XML & binary bplist00) + Tier 1 vs Tier 2 classifier."""

from __future__ import annotations

import plistlib
import struct
from pathlib import PurePosixPath
from typing import Any, Literal

from ..abstractions import LocalPrefixFilesystem, PrefixFilesystem
from ..models import AppBundleInfo, InvalidAppBundleError

MACHO_MAGICS = {
    0xFEEDFACE,
    0xFEEDFACF,
    0xCEFAEDFE,
    0xCFFAEDFE,
    0xCAFEBABE,
    0xBEBAFECA,
}

_GUI_FRAMEWORK_MARKERS = (
    b"AppKit.framework",
    b"Cocoa.framework",
    b"SwiftUI.framework",
    b"Metal.framework",
)


def is_macho_bytes(data: bytes) -> bool:
    if len(data) < 4:
        return False
    magic = struct.unpack_from(">I", data, 0)[0]
    return magic in MACHO_MAGICS


class AppBundleParser:
    """Parses macOS .app bundles offline using stdlib plistlib."""

    def __init__(self, fs: PrefixFilesystem | None = None) -> None:
        self.fs = fs or LocalPrefixFilesystem()

    def parse(
        self,
        app_path: str,
        *,
        require_executable: bool = True,
        mode: Literal["auto", "cli", "gui"] = "auto",
    ) -> AppBundleInfo:
        norm = app_path.replace("\\", "/").rstrip("/")
        plist_path = f"{norm}/Contents/Info.plist"
        if not self.fs.exists(plist_path):
            raise InvalidAppBundleError(f"Missing Contents/Info.plist in bundle: {norm}")

        raw_plist = self.fs.read_bytes(plist_path)
        is_binary = raw_plist.startswith(b"bplist00")
        try:
            plist_data: dict[str, Any] = plistlib.loads(raw_plist)
        except Exception as exc:
            raise InvalidAppBundleError(f"Malformed Info.plist in '{norm}': {exc}") from exc

        if not isinstance(plist_data, dict):
            raise InvalidAppBundleError(f"Info.plist root is not a dict in '{norm}'")

        exe_name = plist_data.get("CFBundleExecutable")
        if not exe_name or not isinstance(exe_name, str):
            raise InvalidAppBundleError(f"Info.plist missing CFBundleExecutable in '{norm}'")

        exe_path = f"{norm}/Contents/MacOS/{exe_name}"
        if require_executable and not self.fs.exists(exe_path):
            raise InvalidAppBundleError(f"Bundle executable missing: {exe_path}")

        bundle_name = (
            plist_data.get("CFBundleDisplayName")
            or plist_data.get("CFBundleName")
            or PurePosixPath(norm).stem
        )
        icon_file = plist_data.get("CFBundleIconFile") or plist_data.get("CFBundleIconName")
        icon_path: str | None = None
        if isinstance(icon_file, str) and icon_file.strip():
            icon_name = icon_file.strip()
            if not icon_name.lower().endswith(".icns"):
                icon_name = f"{icon_name}.icns"
            candidate_icon = f"{norm}/Contents/Resources/{icon_name}"
            if self.fs.exists(candidate_icon):
                icon_path = candidate_icon
            else:
                icon_path = candidate_icon

        version = plist_data.get("CFBundleShortVersionString") or plist_data.get("CFBundleVersion")
        tier, is_gui = self._classify_tier(plist_data, exe_path, mode=mode)

        return AppBundleInfo(
            bundle_path=norm,
            bundle_name=str(bundle_name),
            bundle_identifier=plist_data.get("CFBundleIdentifier"),
            executable_name=exe_name,
            executable_path=exe_path,
            icon_path=icon_path,
            version=str(version) if version is not None else None,
            min_macos=plist_data.get("LSMinimumSystemVersion"),
            tier=tier,
            is_gui=is_gui,
            is_binary_plist=is_binary,
        )

    def _classify_tier(
        self,
        plist_data: dict[str, Any],
        exe_path: str,
        *,
        mode: Literal["auto", "cli", "gui"] = "auto",
    ) -> tuple[Literal["darling", "osx_kvm"], bool]:
        if mode == "cli":
            return "darling", False
        if mode == "gui":
            return "osx_kvm", True

        has_cocoa_keys = any(
            bool(plist_data.get(k))
            for k in ("NSMainNibFile", "NSMainStoryboardFile", "NSPrincipalClass")
        )
        background_only = bool(plist_data.get("LSBackgroundOnly")) or bool(plist_data.get("LSUIElement"))

        links_gui_framework = False
        if self.fs.exists(exe_path):
            try:
                bin_bytes = self.fs.read_bytes(exe_path)
                links_gui_framework = any(marker in bin_bytes for marker in _GUI_FRAMEWORK_MARKERS)
            except OSError:
                links_gui_framework = False

        if (background_only and not has_cocoa_keys and not links_gui_framework):
            return "darling", False

        if has_cocoa_keys or links_gui_framework:
            return "osx_kvm", True

        # Default .app bundle without explicit background-only flag runs in GUI OSX-KVM
        return "osx_kvm", True
