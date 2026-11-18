"""Main HardwareTuner orchestrator tying RAM, storage, power, and glass configs together."""

from __future__ import annotations

import json

from kite_hw_tune.abstractions import Clock, CmdRunner, EnvWriter, ProcFs, SysFs
from kite_hw_tune.models import (
    HardwareProfile,
    PowerSource,
    SystemPaths,
    TuneResult,
)
from kite_hw_tune.power import (
    apply_power_profile,
    build_blur_profile,
    build_power_profile,
    detect_power_source,
    load_glass_settings,
    render_hypr_runtime_conf,
)
from kite_hw_tune.ram import (
    apply_memory_tuning,
    build_memory_profile,
    build_subsystems_profile,
    detect_ram_mb,
)
from kite_hw_tune.storage import apply_storage_schedulers, detect_storage_devices

HASWELL_ENV_CONTENT = (
    "MESA_LOADER_DRIVER_OVERRIDE=crocus\n"
    "LIBVA_DRIVER_NAME=i965\n"
)


class HardwareTuner:
    """Coordinates hardware telemetry detection and profile application."""

    def __init__(
        self,
        *,
        proc_fs: ProcFs,
        sys_fs: SysFs,
        cmd: CmdRunner,
        env_writer: EnvWriter,
        clock: Clock,
        paths: SystemPaths | None = None,
    ) -> None:
        self.proc_fs = proc_fs
        self.sys_fs = sys_fs
        self.cmd = cmd
        self.env_writer = env_writer
        self.clock = clock
        self.paths = paths or SystemPaths()

    def collect_profile(
        self,
        *,
        ram_mb_override: int | None = None,
        power_override: PowerSource | None = None,
        warnings: list[str] | None = None,
    ) -> HardwareProfile:
        """Detect or simulate the full HardwareProfile matching Schema v1."""
        if ram_mb_override is not None:
            if ram_mb_override <= 0:
                raise ValueError(f"--ram-mb must be positive, got {ram_mb_override}")
            ram_mb = ram_mb_override
        else:
            ram_mb = detect_ram_mb(self.proc_fs)

        source: PowerSource = (
            power_override
            if power_override is not None
            else detect_power_source(self.sys_fs)
        )
        memory = build_memory_profile(ram_mb)
        subsystems = build_subsystems_profile(memory.tier, source)
        power = build_power_profile(source)
        settings = load_glass_settings(
            self.env_writer,
            self.paths.settings_file,
            warnings=warnings,
        )
        blur = build_blur_profile(memory.tier, source, settings)
        storage = detect_storage_devices(self.sys_fs, warnings=warnings)

        return HardwareProfile(
            schema_version=1,
            ram_mb=ram_mb,
            memory=memory,
            power=power,
            blur=blur,
            storage=storage,
            subsystems=subsystems,
        )

    def _write_outputs(
        self,
        profile: HardwareProfile,
        *,
        warnings: list[str],
        write_env_file: bool = False,
    ) -> list[str]:
        written: list[str] = []
        settings = load_glass_settings(
            self.env_writer,
            self.paths.settings_file,
            warnings=warnings,
        )

        profile_json = json.dumps(profile.to_dict(), indent=2) + "\n"
        self.env_writer.write_text(self.paths.output_profile, profile_json)
        written.append(self.paths.output_profile)

        runtime_conf = render_hypr_runtime_conf(
            profile.blur,
            settings,
            tier=profile.memory.tier,
            source=profile.power.source,
        )
        self.env_writer.write_text(self.paths.runtime_conf, runtime_conf)
        written.append(self.paths.runtime_conf)

        if write_env_file:
            self.env_writer.write_text(self.paths.env_file, HASWELL_ENV_CONTENT)
            written.append(self.paths.env_file)

        return written

    def run_hw_tune(
        self,
        *,
        ram_mb_override: int | None = None,
        power_override: PowerSource | None = None,
        apply_system: bool = True,
        write_files: bool = True,
        write_env_file: bool = False,
    ) -> TuneResult:
        """Execute full boot-time hardware tuning (RAM, storage, power, glass, profile JSON)."""
        warnings: list[str] = []
        profile = self.collect_profile(
            ram_mb_override=ram_mb_override,
            power_override=power_override,
            warnings=warnings,
        )

        written_files: list[str] = []
        if apply_system:
            mem_warnings = apply_memory_tuning(
                profile.memory,
                self.cmd,
                self.env_writer,
                sysctl_conf_path=self.paths.sysctl_runtime_file,
                dry_run=False,
            )
            warnings.extend(mem_warnings)
            if self.env_writer.exists(self.paths.sysctl_runtime_file):
                written_files.append(self.paths.sysctl_runtime_file)

            apply_storage_schedulers(self.sys_fs, apply=True, warnings=warnings)
            apply_power_profile(
                self.sys_fs,
                self.cmd,
                profile.power,
                apply=True,
                warnings=warnings,
            )

        if write_files:
            written_files.extend(
                self._write_outputs(
                    profile,
                    warnings=warnings,
                    write_env_file=write_env_file,
                )
            )

        if apply_system and self.cmd.which("hyprctl"):
            self.cmd.run(["hyprctl", "reload"])

        history = [list(argv) for argv in getattr(self.cmd, "history", [])]
        return TuneResult(
            profile=profile,
            warnings=warnings,
            commands_run=history,
            written_files=written_files,
        )

    def run_power_tune(
        self,
        *,
        ram_mb_override: int | None = None,
        power_override: PowerSource | None = None,
        apply_system: bool = True,
        write_files: bool = True,
    ) -> TuneResult:
        """Execute AC/Battery transition tuning (power knobs + glass blur + profile JSON)."""
        warnings: list[str] = []
        profile = self.collect_profile(
            ram_mb_override=ram_mb_override,
            power_override=power_override,
            warnings=warnings,
        )

        if apply_system:
            apply_power_profile(
                self.sys_fs,
                self.cmd,
                profile.power,
                apply=True,
                warnings=warnings,
            )

        written_files: list[str] = []
        if write_files:
            written_files.extend(self._write_outputs(profile, warnings=warnings))

        if apply_system and self.cmd.which("hyprctl"):
            self.cmd.run(["hyprctl", "reload"])

        history = [list(argv) for argv in getattr(self.cmd, "history", [])]
        return TuneResult(
            profile=profile,
            warnings=warnings,
            commands_run=history,
            written_files=written_files,
        )
