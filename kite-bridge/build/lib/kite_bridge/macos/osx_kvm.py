"""Tier 2 macOS execution: OSX-KVM Haswell bridge with /dev/kvm gate, VirtIO-FS, and hibernate."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Literal

from ..abstractions import (
    HwProfileReader,
    LocalPrefixFilesystem,
    PosixSystemProbe,
    PrefixFilesystem,
    ProcessRunner,
    QmpClient,
    SubprocessRunner,
    SystemProbe,
)
from ..config import BridgeConfig, haswell_base_env
from ..hw_profile import JsonHwProfileReader
from ..models import HwProfile, KvmUnavailableError, MissingToolError, QemuLaunchSpec, QmpError
from .qmp import QmpLifecycleManager

REQUIRED_HASWELL_CPU_ARG = "Haswell-noTSX,+invtsc,vendor=GenuineIntel"


@dataclass(frozen=True)
class KvmPreflightResult:
    kvm_available: bool
    kvm_rw: bool
    qemu_bin: str | None
    assets_present: bool
    vm_ram_mb: int
    hugepages_enabled: bool
    warnings: tuple[str, ...] = ()


def check_kvm_preflight(
    *,
    probe: SystemProbe,
    runner: ProcessRunner,
    fs: PrefixFilesystem,
    hw_profile: HwProfile,
    osx_kvm_dir: str,
    allow_4g: bool = False,
    require_assets: bool = True,
    require_qemu: bool = True,
) -> KvmPreflightResult:
    """Mandatory /dev/kvm preflight gate before invoking Tier 2 OSX-KVM."""
    if not (probe.exists("/dev/kvm") and probe.is_char_device("/dev/kvm")):
        raise KvmUnavailableError(
            "OSX-KVM requires /dev/kvm (Intel VT-x/EPT). Enable Virtualization Technology in "
            "HP Folio 9480m BIOS and load `kvm_intel` (`modprobe kvm_intel`)."
        )
    if not probe.access_rw("/dev/kvm"):
        raise KvmUnavailableError(
            "/dev/kvm exists but is not readable/writable by current user. "
            "Add user to `kvm` group (`sudo usermod -aG kvm $USER`) and re-login."
        )

    qemu_bin = runner.which("qemu-system-x86_64")
    if require_qemu and not qemu_bin:
        raise MissingToolError("qemu-system-x86_64", "Install `qemu-system-x86` for Tier 2 macOS execution.")

    required_assets = ("OpenCore.qcow2", "macOS.qcow2", "OVMF_CODE.fd", "OVMF_VARS.fd")
    missing_assets = [name for name in required_assets if not fs.exists(f"{osx_kvm_dir}/{name}")]
    if require_assets and missing_assets:
        raise MissingToolError(
            f"OSX-KVM asset(s): {', '.join(missing_assets)}",
            f"Run `scripts/provision-macos.sh` to populate {osx_kvm_dir}.",
        )

    warnings: list[str] = []
    if hw_profile.tier == "4G":
        if not allow_4g:
            raise KvmUnavailableError(
                "Host has 4G RAM; OSX-KVM Tier 2 GUI VM is gated on 4G unless allow_4g=True (--force) is specified."
            )
        vm_ram_mb = 2048
        hugepages = False
        warnings.append("Host has 4G RAM; OSX-KVM capped at 2048 MB and relies heavily on zram.")
    elif hw_profile.tier == "16G":
        vm_ram_mb = 6144
        hugepages = bool(hw_profile.osx_kvm_hugepages_on_demand and probe.exists("/dev/hugepages"))
        if hw_profile.osx_kvm_hugepages_on_demand and not probe.exists("/dev/hugepages"):
            warnings.append("/dev/hugepages not mounted; falling back to memory-backend-memfd.")
    else:
        vm_ram_mb = 4096
        hugepages = False

    return KvmPreflightResult(
        kvm_available=True,
        kvm_rw=True,
        qemu_bin=qemu_bin or "qemu-system-x86_64",
        assets_present=not missing_assets,
        vm_ram_mb=vm_ram_mb,
        hugepages_enabled=hugepages,
        warnings=tuple(warnings),
    )


class OsxKvmBridge:
    """Tier 2 macOS GUI runner using OSX-KVM Haswell passthrough + VirtIO-FS + QMP hibernate."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        hw_reader: HwProfileReader | None = None,
        qmp_client: QmpClient | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self.hw_reader = hw_reader or JsonHwProfileReader(probe=self.probe)
        self.qmp = QmpLifecycleManager(qmp_client)

    @property
    def osx_kvm_dir(self) -> str:
        return f"{self.config.macos_dir}/osx-kvm"

    @property
    def runtime_dir(self) -> str:
        return f"{self.config.macos_dir}/run"

    @property
    def qmp_socket(self) -> str:
        return f"{self.runtime_dir}/qmp.sock"

    @property
    def virtiofs_socket(self) -> str:
        return f"{self.runtime_dir}/virtiofsd.sock"

    def _read_osk(self) -> str:
        osk_file = f"{self.osx_kvm_dir}/osk.txt"
        if self.fs.exists(osk_file):
            val = self.fs.read_text(osk_file).strip()
            if val:
                return val
        return "KITE-OS-PROVISIONED-APPLE-SMC-KEY"

    def build_qemu_command(
        self,
        *,
        app_target: str | None = None,
        hw_profile: HwProfile | None = None,
        allow_4g: bool = False,
        resume_tag: str | None = None,
        display_mode: Literal["vnc", "spice"] = "vnc",
        ssh_port: int = 10022,
        vnc_display: int = 0,
        spice_port: int = 15900,
        require_preflight_tools: bool = True,
    ) -> QemuLaunchSpec:
        profile = hw_profile or self.hw_reader.read(self.config.hw_profile_path)
        preflight = check_kvm_preflight(
            probe=self.probe,
            runner=self.runner,
            fs=self.fs,
            hw_profile=profile,
            osx_kvm_dir=self.osx_kvm_dir,
            allow_4g=allow_4g,
            require_assets=require_preflight_tools,
            require_qemu=require_preflight_tools,
        )

        smp_arg = "2,cores=2,threads=1,sockets=1" if profile.tier == "4G" else "4,cores=2,threads=2,sockets=1"
        vm_ram = preflight.vm_ram_mb
        qemu_bin = preflight.qemu_bin or "qemu-system-x86_64"

        qemu_argv: list[str] = [
            qemu_bin,
            "-enable-kvm",
            "-machine",
            "q35,accel=kvm",
            "-cpu",
            REQUIRED_HASWELL_CPU_ARG,
            "-smp",
            smp_arg,
            "-m",
            str(vm_ram),
        ]

        if preflight.hugepages_enabled:
            qemu_argv.extend(
                [
                    "-mem-prealloc",
                    "-object",
                    f"memory-backend-file,id=mem,size={vm_ram}M,mem-path=/dev/hugepages,share=on",
                ]
            )
        else:
            qemu_argv.extend(
                [
                    "-object",
                    f"memory-backend-memfd,id=mem,size={vm_ram}M,share=on",
                ]
            )

        qemu_argv.extend(
            [
                "-numa",
                "node,memdev=mem",
                "-drive",
                f"if=pflash,format=raw,readonly=on,file={self.osx_kvm_dir}/OVMF_CODE.fd",
                "-drive",
                f"if=pflash,format=raw,file={self.osx_kvm_dir}/OVMF_VARS.fd",
                "-device",
                f'isa-applesmc,osk={self._read_osk()}',
                "-device",
                "ich9-ahci,id=sata",
                "-drive",
                f"id=OpenCoreBoot,if=none,format=qcow2,file={self.osx_kvm_dir}/OpenCore.qcow2",
                "-device",
                "ide-hd,bus=sata.0,drive=OpenCoreBoot",
                "-drive",
                f"id=MacHDD,if=none,format=qcow2,cache=writeback,discard=unmap,file={self.osx_kvm_dir}/macOS.qcow2",
                "-device",
                "virtio-blk-pci,drive=MacHDD",
                "-chardev",
                f"socket,id=char0,path={self.virtiofs_socket}",
                "-device",
                "vhost-user-fs-pci,id=kite_home_fs,queue-size=1024,chardev=char0,tag=kite_home",
                "-netdev",
                f"user,id=net0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22,hostfwd=tcp:127.0.0.1:15901-:5900",
                "-device",
                "virtio-net-pci,netdev=net0,mac=52:54:00:c9:18:27",
                "-qmp",
                f"unix:{self.qmp_socket},server=on,wait=off",
            ]
        )

        if display_mode == "spice":
            qemu_argv.extend(
                [
                    "-device",
                    "qxl-vga",
                    "-spice",
                    f"port={spice_port},addr=127.0.0.1,disable-ticketing=on",
                ]
            )
            viewer_cmd = ["spicy", "-h", "127.0.0.1", "-p", str(spice_port)]
        else:
            qemu_argv.extend(
                [
                    "-vga",
                    "std",
                    "-display",
                    "none",
                    "-vnc",
                    f"127.0.0.1:{vnc_display}",
                ]
            )
            viewer_cmd = ["vncviewer", f"127.0.0.1:{5900 + vnc_display}"]

        if resume_tag:
            qemu_argv.extend(["-loadvm", resume_tag])

        virtiofsd_bin = self.runner.which("virtiofsd") or "virtiofsd"
        virtiofsd_argv = [
            virtiofsd_bin,
            f"--socket-path={self.virtiofs_socket}",
            f"--shared-dir={self.config.home_dir}",
            "--cache=auto",
        ]

        if app_target:
            bridge_argv = [
                "ssh",
                "-p",
                str(ssh_port),
                "kite@127.0.0.1",
                f"open -a {shlex.quote(app_target)}",
            ]
        else:
            bridge_argv = viewer_cmd

        return QemuLaunchSpec(
            qemu_argv=qemu_argv,
            virtiofsd_argv=virtiofsd_argv,
            bridge_argv=bridge_argv,
            qmp_socket=self.qmp_socket,
            virtiofs_socket=self.virtiofs_socket,
            hugepages_enabled=preflight.hugepages_enabled,
            vm_ram_mb=vm_ram,
            resume_tag=resume_tag,
            warnings=list(preflight.warnings),
        )

    def launch_app(
        self,
        app_target: str,
        *,
        resume: bool = True,
        allow_4g: bool = False,
        dry_run: bool = False,
        hw_profile: HwProfile | None = None,
        hw_profile_path: str | None = None,
    ) -> QemuLaunchSpec:
        """Start (or reuse running) OSX-KVM guest and forward app launch."""
        active_profile = hw_profile or (
            self.hw_reader.read(hw_profile_path) if hw_profile_path else None
        )
        # Check if VM is already running via QMP
        if not dry_run and self.probe.exists(self.qmp_socket):
            try:
                status = self.qmp.query_status(self.qmp_socket)
                if status == "running":
                    spec = self.build_qemu_command(
                        app_target=app_target,
                        hw_profile=active_profile,
                        allow_4g=allow_4g,
                        require_preflight_tools=False,
                    )
                    self.runner.run(spec.bridge_argv, env=haswell_base_env(), check=False)
                    return spec
            except QmpError:
                pass

        resume_tag = "kite-idle" if (resume and self.fs.exists(f"{self.runtime_dir}/kite-idle.state")) else None
        spec = self.build_qemu_command(
            app_target=app_target,
            hw_profile=active_profile,
            allow_4g=allow_4g,
            resume_tag=resume_tag,
            require_preflight_tools=not dry_run,
        )
        if dry_run:
            return spec

        self.fs.mkdir(self.runtime_dir, parents=True)
        env = haswell_base_env()
        self.runner.spawn(spec.virtiofsd_argv, env=env)
        self.runner.spawn(spec.qemu_argv, env=env)
        self.runner.run(spec.bridge_argv, env=env, check=False)
        return spec

    def hibernate(self, *, tag: str = "kite-idle") -> tuple[bool, str | None]:
        saved, note = self.qmp.hibernate(self.qmp_socket, tag=tag)
        if saved:
            self.fs.mkdir(self.runtime_dir, parents=True)
            self.fs.write_text(f"{self.runtime_dir}/{tag}.state", "hibernated\n")
        return saved, note

    def resume(self, *, tag: str = "kite-idle", allow_4g: bool = False) -> QemuLaunchSpec:
        spec = self.build_qemu_command(
            resume_tag=tag,
            allow_4g=allow_4g,
            require_preflight_tools=True,
        )
        env = haswell_base_env()
        self.fs.mkdir(self.runtime_dir, parents=True)
        self.runner.spawn(spec.virtiofsd_argv, env=env)
        self.runner.spawn(spec.qemu_argv, env=env)
        return spec
