"""Desktop entry generator & scanner implementing PROJECT.md Interface Contract #6."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from .abstractions import LocalPrefixFilesystem, PrefixFilesystem
from .config import BridgeConfig
from .models import DesktopEntrySpec, Platform, RouteDecision

PLATFORM_TAGS = {
    Platform.WIN: "[Win]",
    Platform.ANDROID: "[Android]",
    Platform.MACOS: "[macOS]",
}


def slugify_app_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "app"


def _escape_desktop_exec_arg(arg: str) -> str:
    """Escape reserved characters inside double-quoted Exec= argument per Desktop Entry spec."""
    escaped = (
        arg.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def infer_app_name(source_path: str, decision: RouteDecision | None = None) -> str:
    if decision and decision.metadata.get("bundle_name"):
        return str(decision.metadata["bundle_name"])
    if decision and decision.metadata.get("package_name"):
        pkg = str(decision.metadata["package_name"])
        return pkg.split(".")[-1].replace("_", " ").title()
    stem = PurePosixPath(source_path.replace("\\", "/").rstrip("/")).stem
    return stem.replace("-", " ").replace("_", " ").strip() or "KiteBridge App"


class DesktopIntegration:
    """Generates and parses ~/.local/share/applications/kitebridge-*.desktop files."""

    def __init__(
        self,
        *,
        fs: PrefixFilesystem | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env()

    def build_spec(
        self,
        decision: RouteDecision,
        *,
        app_name: str | None = None,
        icon: str | None = None,
    ) -> DesktopEntrySpec:
        resolved_name = app_name or infer_app_name(decision.path, decision)
        tag = PLATFORM_TAGS.get(decision.platform, "[App]")
        slug = slugify_app_name(resolved_name)
        desktop_filename = f"kitebridge-{decision.platform.value}-{slug}.desktop"
        desktop_path = f"{self.config.applications_dir}/{desktop_filename}"
        exec_target = decision.path
        if decision.platform == Platform.ANDROID and decision.metadata.get("package_name"):
            exec_target = decision.path
        return DesktopEntrySpec(
            slug=slug,
            app_name=resolved_name,
            platform=decision.platform,
            platform_tag=tag,
            handler=decision.handler,
            source_path=decision.path,
            exec_command=f"kite-bridge open {_escape_desktop_exec_arg(exec_target)}",
            icon=icon or f"kitebridge-{decision.platform.value}",
            mime_types=(decision.mime_type,) if decision.mime_type else (),
            desktop_path=desktop_path,
        )

    def render_desktop_file(self, spec: DesktopEntrySpec) -> str:
        display_name = spec.app_name
        if not display_name.startswith(spec.platform_tag):
            display_name = f"{spec.platform_tag} {display_name}"
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.5",
            f"Name={display_name}",
            f"Comment=Launched via KiteBridge ({spec.handler})",
            f"Exec={spec.exec_command}",
            f"Icon={spec.icon}",
            "Terminal=false",
            "Categories=Utility;Application;",
            f"X-KiteBridge-Platform={spec.platform.value}",
            f"X-KiteBridge-Handler={spec.handler}",
            f"X-KiteBridge-SourcePath={spec.source_path}",
            f"X-KiteBridge-Tag={spec.platform_tag}",
        ]
        if spec.mime_types:
            lines.append(f"MimeType={';'.join(spec.mime_types)};")
        return "\n".join(lines) + "\n"

    def write_desktop_entry(self, spec: DesktopEntrySpec) -> str:
        self.fs.mkdir(self.config.applications_dir, parents=True)
        content = self.render_desktop_file(spec)
        self.fs.write_text(spec.desktop_path, content)
        return spec.desktop_path

    def list_entries(
        self,
        *,
        platform_filter: Literal["win", "android", "macos", "all"] = "all",
    ) -> list[DesktopEntrySpec]:
        apps_dir = self.config.applications_dir
        if not self.fs.exists(apps_dir):
            return []
        paths = self.fs.glob(apps_dir, "kitebridge-*.desktop")
        entries: list[DesktopEntrySpec] = []
        for path in paths:
            parsed = self.parse_desktop_file(path)
            if parsed is None:
                continue
            if platform_filter != "all" and parsed.platform.value != platform_filter:
                continue
            entries.append(parsed)
        return entries

    def parse_desktop_file(self, path: str) -> DesktopEntrySpec | None:
        raw = self.fs.read_text(path)
        kv: dict[str, str] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("[") or "=" not in stripped:
                continue
            k, v = stripped.split("=", 1)
            kv[k.strip()] = v.strip()

        plat_raw = kv.get("X-KiteBridge-Platform", "unknown")
        try:
            platform = Platform(plat_raw)
        except ValueError:
            platform = Platform.UNKNOWN

        tag = kv.get("X-KiteBridge-Tag") or PLATFORM_TAGS.get(platform, "[App]")
        posix_path = path.replace("\\", "/")
        name_val = kv.get("Name", PurePosixPath(posix_path).stem)
        clean_name = name_val[len(tag):].strip() if name_val.startswith(tag) else name_val
        stem = PurePosixPath(posix_path).stem
        prefix = f"kitebridge-{platform.value}-"
        slug = stem[len(prefix):] if stem.startswith(prefix) else stem
        mimes = tuple(m for m in kv.get("MimeType", "").split(";") if m)
        return DesktopEntrySpec(
            slug=slug,
            app_name=clean_name,
            platform=platform,
            platform_tag=tag,
            handler=kv.get("X-KiteBridge-Handler", ""),
            source_path=kv.get("X-KiteBridge-SourcePath", ""),
            exec_command=kv.get("Exec", ""),
            icon=kv.get("Icon", ""),
            mime_types=mimes,
            desktop_path=path,
        )
