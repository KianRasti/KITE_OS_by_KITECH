"""Tests for Tier 1 Darling CLI execution."""

from __future__ import annotations

import plistlib

import pytest

from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import FakeProcessRunner, FakeSystemProbe, InMemoryPrefixFilesystem
from kite_bridge.macos.darling import DarlingRunner
from kite_bridge.models import MissingToolError


def test_darling_runner_exec_and_env() -> None:
    fs = InMemoryPrefixFilesystem()
    probe = FakeSystemProbe()
    runner = FakeProcessRunner(available_binaries={"darling": "/usr/bin/darling"})
    runner.set_result("darling", returncode=42, stdout="macho-ok")
    cfg = BridgeConfig.from_env(probe=probe, env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})
    darling = DarlingRunner(runner=runner, probe=probe, fs=fs, config=cfg)

    fs.write_bytes(
        "/apps/CliTool.app/Contents/Info.plist",
        plistlib.dumps({"CFBundleExecutable": "clitool", "LSBackgroundOnly": True}),
    )
    res = darling.run("/apps/CliTool.app", args=["--version"])
    assert res.returncode == 42
    assert res.stdout == "macho-ok"
    assert res.command == ["/usr/bin/darling", "shell", "/apps/CliTool.app/Contents/MacOS/clitool", "--version"]
    assert res.env["DPREFIX"] == "/var/lib/kitebridge/macos/darling/prefix"
    assert res.env["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
    assert res.env["LIBVA_DRIVER_NAME"] == "i965"


def test_darling_missing_raises_error() -> None:
    darling = DarlingRunner(runner=FakeProcessRunner(), probe=FakeSystemProbe(), fs=InMemoryPrefixFilesystem())
    with pytest.raises(MissingToolError):
        darling.run("/tmp/tool")
