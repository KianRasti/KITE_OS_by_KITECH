"""Glass Installer Wizard planner and Wayland QML / headless CLI runner."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Mapping

from .abstractions import ProcessRunner, SubprocessRunner
from .config import BridgeConfig
from .desktop import DesktopIntegration, PLATFORM_TAGS, infer_app_name, slugify_app_name
from .models import Platform, RouteDecision, WizardPlan


def find_wizard_qml() -> str:
    pkg_dir = Path(__file__).resolve().parent.parent
    local_qml = pkg_dir / "mime" / "GlassInstallerWizard.qml"
    if local_qml.exists():
        return str(local_qml)
    return "/usr/local/share/kite-bridge/GlassInstallerWizard.qml"


class InstallerWizard:
    """Builds and runs Glass Installer Wizard plans on Wayland or headlessly via CLI."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        config: BridgeConfig | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.config = config or BridgeConfig.from_env()
        self.env = env if env is not None else os.environ

    def build_plan(
        self,
        decision: RouteDecision,
        *,
        app_name: str | None = None,
        icon_path: str | None = None,
        prefix: str | None = None,
        no_wizard: bool = False,
        dry_run: bool = False,
    ) -> WizardPlan:
        name = app_name or infer_app_name(decision.path, decision)
        slug = slugify_app_name(name)
        tag = PLATFORM_TAGS.get(decision.platform, "[App]")
        desktop_path = f"{self.config.applications_dir}/kitebridge-{decision.platform.value}-{slug}.desktop"
        resolved_icon = icon_path or f"kitebridge-{decision.platform.value}"

        if decision.platform == Platform.WIN:
            target_prefix = prefix or self.config.wine_prefix
            steps = [
                f"Verify Wine-CachyOS + /dev/ntsync prefix ({target_prefix})",
                "Enforce DXVK 1.10.3 (d3d9, d3d10core, d3d11, dxgi) and WineD3D OpenGL 4.6 (crocus) for DX12",
                f"Extract icon -> {resolved_icon}",
                f"Register desktop launcher -> {desktop_path}",
            ]
        elif decision.platform == Platform.ANDROID:
            target_prefix = f"{self.config.data_dir}/waydroid"
            steps = [
                "Ensure Waydroid multi-window Wayland session (persist.waydroid.multi_windows=true)",
                "Convert .aab via bundletool --mode=universal (if .aab) and install into Waydroid",
                f"Extract icon -> {resolved_icon}",
                f"Register desktop launcher -> {desktop_path}",
            ]
        else:
            target_prefix = f"{self.config.macos_dir}"
            steps = [
                f"Prepare macOS runtime ({decision.handler})",
                f"Extract icon -> {resolved_icon}",
                f"Register desktop launcher -> {desktop_path}",
            ]

        has_wayland = bool(self.env.get("WAYLAND_DISPLAY"))
        qml_bin = self.runner.which("qml6") or self.runner.which("quickshell")
        mode = "dry-run" if dry_run else ("qml" if (not no_wizard and has_wayland and qml_bin) else "cli")

        return WizardPlan(
            app_name=name,
            platform=decision.platform,
            platform_tag=tag,
            handler=decision.handler,
            source_path=decision.path,
            target_prefix=target_prefix,
            desktop_entry_path=desktop_path,
            icon_path=resolved_icon,
            dxvk_version=decision.dxvk_version,
            steps=steps,
            env=dict(decision.env),
            mode=mode,  # type: ignore[arg-type]
        )

    def launch_qml(self, plan: WizardPlan) -> bool:
        if plan.mode != "qml":
            return False
        qml_bin = self.runner.which("qml6") or self.runner.which("quickshell")
        if not qml_bin:
            return False
        qml_file = find_wizard_qml()
        run_env = dict(plan.env)
        plan_payload = json.dumps(plan.to_dict())
        run_env["KITEBRIDGE_WIZARD_PLAN"] = plan_payload
        cmd = [qml_bin, qml_file]
        if PurePosixPath(qml_bin.replace("\\", "/")).name == "qml6":
            cmd.extend(["--", f"--plan={plan_payload}"])
        res = self.runner.run(cmd, env=run_env, check=False)
        return res.returncode == 0
