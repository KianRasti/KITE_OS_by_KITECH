"""Tier 1 macOS execution: Darling CLI/Mach-O runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..abstractions import (
    LocalPrefixFilesystem,
    PosixSystemProbe,
    PrefixFilesystem,
    ProcessRunner,
    SubprocessRunner,
    SystemProbe,
)
from ..config import BridgeConfig, haswell_base_env
from ..models import MissingToolError
from .bundle import AppBundleParser


@dataclass(frozen=True)
class DarlingExecResult:
    command: list[str]
    env: dict[str, str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class DarlingRunner:
    """Executes macOS CLI Mach-O binaries or headless bundles via `darling shell`."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        probe: SystemProbe | None = None,
        fs: PrefixFilesystem | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.probe = probe or PosixSystemProbe()
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env(probe=self.probe)
        self.bundle_parser = AppBundleParser(fs=self.fs)

    @property
    def default_prefix(self) -> str:
        return f"{self.config.macos_dir}/darling/prefix"

    def build_env(self, *, dprefix: str | None = None, extra_env: Mapping[str, str] | None = None) -> dict[str, str]:
        env = haswell_base_env()
        if extra_env:
            env.update(extra_env)
        env["DPREFIX"] = (dprefix or self.default_prefix).replace("\\", "/")
        return env

    def resolve_executable(self, target_path: str) -> str:
        norm = target_path.replace("\\", "/").rstrip("/")
        if norm.endswith(".app") and self.fs.exists(f"{norm}/Contents/Info.plist"):
            info = self.bundle_parser.parse(norm, require_executable=False, mode="cli")
            return info.executable_path
        return norm

    def build_command(self, target_path: str, args: Sequence[str] = ()) -> list[str]:
        exe = self.resolve_executable(target_path)
        return ["darling", "shell", exe, *args]

    def run(
        self,
        target_path: str,
        args: Sequence[str] = (),
        *,
        dprefix: str | None = None,
        dry_run: bool = False,
        extra_env: Mapping[str, str] | None = None,
    ) -> DarlingExecResult:
        cmd = self.build_command(target_path, args=args)
        env = self.build_env(dprefix=dprefix, extra_env=extra_env)
        if dry_run:
            return DarlingExecResult(command=cmd, env=env, returncode=0)

        darling_bin = self.runner.which("darling")
        if not darling_bin:
            raise MissingToolError("darling", "Run `scripts/provision-macos.sh` to install Darling.")
        self.fs.mkdir(env["DPREFIX"], parents=True)
        full_cmd = [darling_bin, *cmd[1:]]
        res = self.runner.run(full_cmd, env=env)
        return DarlingExecResult(
            command=full_cmd,
            env=env,
            returncode=res.returncode,
            stdout=res.stdout,
            stderr=res.stderr,
        )
