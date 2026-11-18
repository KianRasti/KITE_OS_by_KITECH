"""Unified CLI for KiteBridge (`kite-bridge <subcommand>`)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from . import LIBVA_DRIVER_PIN, MESA_DRIVER_PIN, REQUIRED_DXVK_VERSION, __version__
from .abstractions import (
    CgroupController,
    HwProfileReader,
    LocalPrefixFilesystem,
    PosixSystemProbe,
    PrefixFilesystem,
    ProcessRunner,
    SubprocessRunner,
    SystemProbe,
)
from .config import BridgeConfig
from .desktop import DesktopIntegration, infer_app_name, slugify_app_name
from .hw_profile import JsonHwProfileReader
from .icons import extract_icon
from .macos.darling import DarlingRunner
from .macos.osx_kvm import REQUIRED_HASWELL_CPU_ARG, OsxKvmBridge
from .mime_router import MimeRouter
from .models import BridgeError, DesktopEntrySpec, Platform
from .waydroid import WaydroidSubsystem
from .wine import WineSubsystem
from .wizard import InstallerWizard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kite-bridge",
        description="KITE_OS Universal App & File Runtime (Windows/Android/macOS)",
    )
    parser.add_argument("--version", action="version", version=f"kite-bridge {__version__}")

    sub = parser.add_subparsers(dest="subcommand", required=True)

    # inspect
    p_inspect = sub.add_parser("inspect", help="Inspect file/bundle routing without executing")
    p_inspect.add_argument("path")
    p_inspect.add_argument("--json", action="store_true", dest="as_json")
    p_inspect.add_argument("--mode", choices=("auto", "cli", "gui"), default="auto")
    p_inspect.add_argument("--prefix", default=None)
    p_inspect.add_argument("--hw-profile", "--profile", dest="hw_profile", default=None)

    # open
    p_open = sub.add_parser("open", help="Open/run a Windows, Android, or macOS file or bundle")
    p_open.add_argument("path")
    p_open.add_argument("--dry-run", action="store_true")
    p_open.add_argument("--json", action="store_true", dest="as_json")
    p_open.add_argument("--mode", choices=("auto", "cli", "gui"), default="auto")
    p_open.add_argument("--prefix", default=None)
    p_open.add_argument("--no-wizard", action="store_true")
    p_open.add_argument("--hw-profile", "--profile", dest="hw_profile", default=None)
    p_open.add_argument("--allow-4g", action="store_true")

    # install
    p_install = sub.add_parser("install", help="Install app, extract icon, and write .desktop entry")
    p_install.add_argument("path")
    p_install.add_argument("--name", default=None)
    p_install.add_argument("--icon", default=None)
    p_install.add_argument("--prefix", default=None)
    p_install.add_argument("--desktop-dir", default=None)
    p_install.add_argument("--no-wizard", action="store_true")
    p_install.add_argument("--dry-run", action="store_true")
    p_install.add_argument("--json", action="store_true", dest="as_json")
    p_install.add_argument("--hw-profile", "--profile", dest="hw_profile", default=None)

    # list
    p_list = sub.add_parser("list", help="List installed KiteBridge .desktop applications")
    p_list.add_argument("--platform", choices=("win", "android", "macos", "all"), default="all")
    p_list.add_argument("--json", action="store_true", dest="as_json")

    # status
    p_status = sub.add_parser("status", help="Probe kernel devices, runtimes, and hardware tier")
    p_status.add_argument("--json", action="store_true", dest="as_json")
    p_status.add_argument("--hw-profile", "--profile", dest="hw_profile", default=None)

    # lifecycle
    p_life = sub.add_parser("lifecycle", help="Manage subsystem lifecycle (RAM-tier freeze/teardown/hibernate)")
    p_life.add_argument("subsystem", nargs="?", choices=("wine", "waydroid", "osx-kvm", "all"), default="all")
    p_life.add_argument(
        "action",
        nargs="?",
        choices=("start", "prewarm", "freeze", "unfreeze", "hibernate", "teardown", "idle-tick", "status"),
        default="status",
    )
    p_life.add_argument("--idle-seconds", "--idle-sec", dest="idle_seconds", type=float, default=0.0)
    p_life.add_argument("--dry-run", action="store_true")
    p_life.add_argument("--json", action="store_true", dest="as_json")
    p_life.add_argument("--hw-profile", "--profile", dest="hw_profile", default=None)

    # setup
    p_setup = sub.add_parser("setup", help="Initialize @kitebridge directories and verify subsystem pins")
    p_setup.add_argument("target", nargs="?", choices=("wine", "waydroid", "macos", "mime", "all"), default="all")
    p_setup.add_argument("--dry-run", action="store_true")
    p_setup.add_argument("--json", action="store_true", dest="as_json")
    p_setup.add_argument("--hw-profile", "--profile", dest="hw_profile", default=None)

    return parser


class KiteBridgeApp:
    """Dependency-injectable CLI controller."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        cgroups: CgroupController | None = None,
        hw_reader: HwProfileReader | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self.hw_reader = hw_reader or JsonHwProfileReader(probe=self.probe)
        self.router = MimeRouter(
            runner=self.runner,
            probe=self.probe,
            fs=self.fs,
            hw_reader=self.hw_reader,
            config=self.config,
        )
        self.waydroid = WaydroidSubsystem(
            runner=self.runner,
            probe=self.probe,
            fs=self.fs,
            cgroups=cgroups,
            hw_reader=self.hw_reader,
            config=self.config,
        )
        self.wine = self.router.wine
        self.desktop = DesktopIntegration(fs=self.fs, config=self.config)
        self.wizard = InstallerWizard(runner=self.runner, config=self.config)

    def run_cli(self, argv: Sequence[str] | None = None) -> int:
        parser = build_parser()
        args = parser.parse_args(list(argv) if argv is not None else None)
        try:
            return self._dispatch(args)
        except BridgeError as exc:
            if getattr(args, "as_json", False):
                print(json.dumps({"error": str(exc), "type": type(exc).__name__}, indent=2))
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1

    def _dispatch(self, args: argparse.Namespace) -> int:
        cmd = args.subcommand
        if cmd == "inspect":
            return self._cmd_inspect(args)
        if cmd == "open":
            return self._cmd_open(args)
        if cmd == "install":
            return self._cmd_install(args)
        if cmd == "list":
            return self._cmd_list(args)
        if cmd == "status":
            return self._cmd_status(args)
        if cmd == "lifecycle":
            return self._cmd_lifecycle(args)
        if cmd == "setup":
            return self._cmd_setup(args)
        return 2

    def _cmd_inspect(self, args: argparse.Namespace) -> int:
        decision = self.router.inspect(
            args.path,
            mode=args.mode,
            prefix=args.prefix,
            hw_profile_path=args.hw_profile,
        )
        payload = decision.to_inspect_dict()
        if args.as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"{decision.path} -> platform={decision.platform.value} handler={decision.handler} "
                f"command={' '.join(decision.command)}"
            )
        return 2 if decision.platform == Platform.UNKNOWN else 0

    def _cmd_open(self, args: argparse.Namespace) -> int:
        decision = self.router.inspect(
            args.path,
            mode=args.mode,
            prefix=args.prefix,
            hw_profile_path=args.hw_profile,
        )
        if decision.platform == Platform.UNKNOWN:
            if args.as_json:
                print(json.dumps(decision.to_inspect_dict(), indent=2))
            else:
                print(f"Unsupported file: {args.path}", file=sys.stderr)
            return 2

        if args.dry_run:
            if args.as_json:
                print(json.dumps(decision.to_inspect_dict(), indent=2))
            else:
                print("DRY-RUN:", " ".join(decision.command))
            return 0

        if decision.platform == Platform.WIN:
            _, res = self.wine.launch(
                args.path,
                prefix=args.prefix,
                dry_run=False,
                extension_override=decision.extension,
                hw_profile_path=args.hw_profile,
            )
            rc = res.returncode if res else 0
        elif decision.platform == Platform.ANDROID:
            _, results = self.waydroid.install_and_launch(
                args.path,
                dry_run=False,
                hw_profile_path=args.hw_profile,
            )
            rc = results[-1].returncode if results else 0
        else:
            if decision.handler == "darling-cli":
                d_res = DarlingRunner(
                    runner=self.runner, probe=self.probe, fs=self.fs, config=self.config
                ).run(args.path, dry_run=False)
                rc = d_res.returncode
            elif decision.handler == "osx-kvm-bridge":
                target = str(decision.metadata.get("bundle_name") or args.path)
                OsxKvmBridge(
                    runner=self.runner,
                    probe=self.probe,
                    fs=self.fs,
                    hw_reader=self.hw_reader,
                    config=self.config,
                ).launch_app(
                    target,
                    allow_4g=args.allow_4g,
                    dry_run=False,
                    hw_profile_path=args.hw_profile,
                )
                rc = 0
            else:
                run_res = self.runner.run(decision.command, env=decision.env, check=False)
                rc = run_res.returncode

        if args.as_json:
            out = decision.to_inspect_dict()
            out["returncode"] = rc
            print(json.dumps(out, indent=2))
        return rc

    def _cmd_install(self, args: argparse.Namespace) -> int:
        decision = self.router.inspect(
            args.path,
            prefix=args.prefix,
            hw_profile_path=args.hw_profile,
        )
        if decision.platform == Platform.UNKNOWN:
            if args.as_json:
                print(json.dumps(decision.to_inspect_dict(), indent=2))
            return 2

        name = args.name or infer_app_name(args.path, decision)
        slug = slugify_app_name(name)
        if args.dry_run:
            plan = self.wizard.build_plan(
                decision,
                app_name=name,
                icon_path=args.icon,
                prefix=args.prefix,
                no_wizard=args.no_wizard,
                dry_run=True,
            )
            if args.as_json:
                print(json.dumps(plan.to_dict(), indent=2))
            else:
                print(f"DRY-RUN install {plan.platform_tag} {plan.app_name} -> {plan.desktop_entry_path}")
            return 0

        if args.icon:
            icon_val = args.icon
        else:
            icon_res = extract_icon(args.path, decision.platform, self.config.icons_dir, slug, fs=self.fs)
            icon_val = icon_res.icon_value

        plan = self.wizard.build_plan(
            decision,
            app_name=name,
            icon_path=icon_val,
            prefix=args.prefix,
            no_wizard=args.no_wizard,
            dry_run=False,
        )
        if plan.mode == "qml":
            self.wizard.launch_qml(plan)

        spec = self.desktop.build_spec(decision, app_name=name, icon=icon_val)
        if getattr(args, "desktop_dir", None):
            target_dir = str(args.desktop_dir).replace("\\", "/").rstrip("/")
            spec = DesktopEntrySpec(
                slug=spec.slug,
                app_name=spec.app_name,
                platform=spec.platform,
                platform_tag=spec.platform_tag,
                handler=spec.handler,
                source_path=spec.source_path,
                exec_command=spec.exec_command,
                icon=spec.icon,
                mime_types=spec.mime_types,
                desktop_path=f"{target_dir}/kitebridge-{spec.platform.value}-{spec.slug}.desktop",
            )
            self.fs.mkdir(target_dir, parents=True)
            self.fs.write_text(spec.desktop_path, self.desktop.render_desktop_file(spec))
            written = spec.desktop_path
        else:
            written = self.desktop.write_desktop_entry(spec)
        if args.as_json:
            payload = plan.to_dict()
            payload["desktop_entry_path"] = written
            print(json.dumps(payload, indent=2))
        else:
            print(f"Installed {spec.platform_tag} {spec.app_name} -> {written}")
        return 0

    def _cmd_list(self, args: argparse.Namespace) -> int:
        entries = self.desktop.list_entries(platform_filter=args.platform)
        if args.as_json:
            payload = {
                "applications": [e.to_dict() for e in entries],
                "count": len(entries),
                "applications_dir": self.config.applications_dir,
                "platform_filter": args.platform,
            }
            print(json.dumps(payload, indent=2))
        else:
            for e in entries:
                print(f"{e.platform_tag} {e.app_name} ({e.handler}) -> {e.desktop_path}")
        return 0

    def _cmd_status(self, args: argparse.Namespace) -> int:
        profile = self.hw_reader.read(args.hw_profile or self.config.hw_profile_path)
        waydroid_prereqs = self.waydroid.check_prerequisites()
        status_payload: dict[str, Any] = {
            "version": __version__,
            "data_dir": self.config.data_dir,
            "applications_dir": self.config.applications_dir,
            "haswell_env": {
                "MESA_LOADER_DRIVER_OVERRIDE": MESA_DRIVER_PIN,
                "LIBVA_DRIVER_NAME": LIBVA_DRIVER_PIN,
            },
            "hw_profile": {
                "ram_mb": profile.ram_mb,
                "tier": profile.tier,
                "power_source": profile.power_source,
                "fallback_used": profile.fallback_used,
            },
            "wine": {
                "dxvk_version": REQUIRED_DXVK_VERSION,
                "wined3d_dx12": True,
                "ntsync_device": self.wine.check_ntsync(),
                "runtime": self.wine.selector.select_runtime(allow_virtual=True).binary,
            },
            "waydroid": {
                "binder": waydroid_prereqs.binder_available,
                "psi": waydroid_prereqs.psi_available,
                "multi_windows": waydroid_prereqs.multi_windows_enabled,
                "arm_translation": waydroid_prereqs.arm_translation,
                "idle_policy": profile.waydroid_idle_policy,
                "teardown_after_sec": profile.waydroid_teardown_after_sec,
                "prewarm": profile.waydroid_prewarm,
            },
            "macos": {
                "kvm_exists": self.probe.exists("/dev/kvm"),
                "kvm_rw": self.probe.access_rw("/dev/kvm"),
                "hugepages_on_demand": profile.osx_kvm_hugepages_on_demand,
                "darling": bool(self.runner.which("darling")),
                "darling_dmg": bool(self.runner.which("darling-dmg")),
                "apfs_fuse": bool(self.runner.which("apfs-fuse")),
                "hfsprogs": bool(self.runner.which("fsck.hfsplus")),
                "qemu": bool(self.runner.which("qemu-system-x86_64")),
            },
        }
        if args.as_json:
            print(json.dumps(status_payload, indent=2))
        else:
            print(
                f"KiteBridge {__version__} | Tier={profile.tier} | DXVK={REQUIRED_DXVK_VERSION} | "
                f"ntsync={status_payload['wine']['ntsync_device']} | kvm={status_payload['macos']['kvm_rw']}"
            )
        return 0

    def _cmd_lifecycle(self, args: argparse.Namespace) -> int:
        profile = self.hw_reader.read(args.hw_profile or self.config.hw_profile_path)
        result: dict[str, Any] = {
            "subsystem": args.subsystem,
            "action": args.action,
            "tier": profile.tier,
            "dry_run": args.dry_run,
        }

        if args.subsystem in ("waydroid", "all"):
            mgr = self.waydroid.lifecycle
            if args.hw_profile:
                mgr.hw_profile_path = args.hw_profile
            if not args.dry_run:
                if args.action == "start":
                    mgr.ensure_active()
                elif args.action == "prewarm":
                    mgr.prewarm(hw_profile_path=args.hw_profile)
                elif args.action == "freeze":
                    mgr.freeze()
                elif args.action == "unfreeze":
                    mgr.unfreeze()
                elif args.action == "teardown":
                    mgr.teardown()
                elif args.action == "idle-tick":
                    mgr.on_idle(now=0.0, hw_profile_path=args.hw_profile)
                    mgr.tick(now=float(args.idle_seconds), hw_profile_path=args.hw_profile)
            result["waydroid"] = mgr.status_dict(hw_profile_path=args.hw_profile)

        if args.subsystem in ("osx-kvm", "all"):
            kvm = OsxKvmBridge(
                runner=self.runner,
                probe=self.probe,
                fs=self.fs,
                hw_reader=self.hw_reader,
                config=self.config,
            )
            if args.action == "hibernate" and not args.dry_run:
                saved, note = kvm.hibernate()
                result["osx_kvm"] = {
                    "hibernated": saved,
                    "note": note,
                    "idle_hibernate_method": "savevm",
                    "resume_method": "loadvm",
                }
            else:
                result["osx_kvm"] = {
                    "hugepages_on_demand": profile.osx_kvm_hugepages_on_demand,
                    "qmp_socket": kvm.qmp_socket,
                    "idle_hibernate_method": "savevm",
                    "resume_method": "loadvm",
                    "haswell_cpu": REQUIRED_HASWELL_CPU_ARG,
                }

        if args.subsystem in ("wine", "all"):
            result["wine"] = {
                "dxvk_version": REQUIRED_DXVK_VERSION,
                "wined3d_dx12": True,
                "ntsync": self.wine.check_ntsync(),
                "prewarm": profile.wine_prewarm,
            }

        if args.as_json:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result))
        return 0

    def _cmd_setup(self, args: argparse.Namespace) -> int:
        dirs = [
            f"{self.config.data_dir}/wine/prefixes",
            f"{self.config.data_dir}/wine/dxvk/{REQUIRED_DXVK_VERSION}",
            f"{self.config.data_dir}/wine/runners",
            f"{self.config.data_dir}/waydroid/images",
            f"{self.config.data_dir}/waydroid/data",
            f"{self.config.data_dir}/waydroid/overlay",
            f"{self.config.data_dir}/waydroid/tools",
            f"{self.config.data_dir}/waydroid/aab-cache",
            f"{self.config.data_dir}/macos/osx-kvm",
            f"{self.config.data_dir}/macos/images",
            f"{self.config.data_dir}/macos/mounts",
            f"{self.config.data_dir}/macos/snapshots",
            f"{self.config.data_dir}/macos/darling/prefix",
            f"{self.config.data_dir}/icons",
            f"{self.config.data_dir}/cache",
            f"{self.config.data_dir}/cgroups",
        ]
        if not args.dry_run:
            for d in dirs:
                self.fs.mkdir(d, parents=True)
        payload = {
            "target": args.target,
            "data_dir": self.config.data_dir,
            "dxvk_version": REQUIRED_DXVK_VERSION,
            "dry_run": args.dry_run,
            "directories": dirs,
            "haswell_env": {
                "MESA_LOADER_DRIVER_OVERRIDE": MESA_DRIVER_PIN,
                "LIBVA_DRIVER_NAME": LIBVA_DRIVER_PIN,
            },
            "wine_user_folders": ["Desktop", "Documents", "Downloads"],
            "waydroid": {
                "persist.waydroid.multi_windows": True,
                "binder_devices": ["/dev/binder", "/dev/hwbinder", "/dev/vndbinder"],
                "arm_translation": "libndk",
                "bundletool_mode": "universal",
            },
            "macos": {
                "mount_tools": ["darling-dmg", "hfsprogs", "apfs-fuse"],
                "cli_runtime": "darling",
                "gui_runtime": "osx-kvm",
                "haswell_cpu": REQUIRED_HASWELL_CPU_ARG,
            },
        }
        if args.as_json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"KiteBridge setup ({args.target}) -> {self.config.data_dir}")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    return KiteBridgeApp().run_cli(argv)
