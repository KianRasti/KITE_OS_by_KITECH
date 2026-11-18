"""Tests for Tier 2 OSX-KVM Haswell bridge, /dev/kvm gate, VirtIO-FS, hugepages, and QMP."""

from __future__ import annotations

import pytest

from kite_bridge.config import BridgeConfig
from kite_bridge.fakes import (
    FakeHwProfileReader,
    FakeProcessRunner,
    FakeQmpClient,
    FakeSystemProbe,
    InMemoryPrefixFilesystem,
)
from kite_bridge.hw_profile import build_tier_profile
from kite_bridge.macos.osx_kvm import OsxKvmBridge
from kite_bridge.models import KvmUnavailableError


def _setup_kvm(tier: str = "16G", *, with_kvm: bool = True, kvm_rw: bool = True, with_hugepages: bool = True):
    probe = FakeSystemProbe()
    if with_kvm:
        probe.add_char_device("/dev/kvm", rw=kvm_rw)
    if with_hugepages:
        probe.add_dir("/dev/hugepages")
    fs = InMemoryPrefixFilesystem()
    cfg = BridgeConfig.from_env(probe=probe, env={"HOME": "/home/kite", "KITEBRIDGE_DATA_DIR": "/var/lib/kitebridge"})
    for asset in ("OpenCore.qcow2", "macOS.qcow2", "OVMF_CODE.fd", "OVMF_VARS.fd"):
        fs.write_bytes(f"{cfg.macos_dir}/osx-kvm/{asset}", b"img")
    runner = FakeProcessRunner(
        available_binaries={
            "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
            "virtiofsd": "/usr/lib/virtiofsd",
        }
    )
    qmp = FakeQmpClient()
    bridge = OsxKvmBridge(
        runner=runner,
        probe=probe,
        fs=fs,
        hw_reader=FakeHwProfileReader(build_tier_profile(tier)),  # type: ignore[arg-type]
        qmp_client=qmp,
        config=cfg,
    )
    return bridge, runner, fs, qmp


def test_kvm_preflight_gates_missing_or_unprivileged_kvm() -> None:
    bridge_no_kvm, runner_no_kvm, _, _ = _setup_kvm("8G", with_kvm=False)
    with pytest.raises(KvmUnavailableError):
        bridge_no_kvm.build_qemu_command()
    assert runner_no_kvm.invocations == []

    bridge_ro_kvm, runner_ro_kvm, _, _ = _setup_kvm("8G", with_kvm=True, kvm_rw=False)
    with pytest.raises(KvmUnavailableError):
        bridge_ro_kvm.build_qemu_command()
    assert runner_ro_kvm.invocations == []


def test_osx_kvm_haswell_cpu_virtiofs_and_ram_tiers() -> None:
    # 16G with hugepages
    bridge_16, _, _, _ = _setup_kvm("16G", with_hugepages=True)
    spec_16 = bridge_16.build_qemu_command(app_target="Pages")
    cmd_str = " ".join(spec_16.qemu_argv)
    assert "-cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel" in cmd_str
    assert "+hle" not in cmd_str and "+rtm" not in cmd_str
    assert "-mem-prealloc" in spec_16.qemu_argv
    assert any("mem-path=/dev/hugepages,share=on" in arg for arg in spec_16.qemu_argv)
    assert any("vhost-user-fs-pci" in arg for arg in spec_16.qemu_argv)
    assert any("virtio-net-pci" in arg for arg in spec_16.qemu_argv)
    assert any("virtio-blk-pci" in arg for arg in spec_16.qemu_argv)
    assert "--shared-dir=/home/kite" in spec_16.virtiofsd_argv
    assert any("127.0.0.1" in arg for arg in spec_16.bridge_argv)

    # 8G uses memfd, not hugepages
    bridge_8, _, _, _ = _setup_kvm("8G", with_hugepages=True)
    spec_8 = bridge_8.build_qemu_command()
    assert spec_8.hugepages_enabled is False
    assert any("memory-backend-memfd,id=mem,size=4096M,share=on" in arg for arg in spec_8.qemu_argv)

    # 4G gated unless allow_4g=True
    bridge_4, _, _, _ = _setup_kvm("4G")
    with pytest.raises(KvmUnavailableError):
        bridge_4.build_qemu_command(allow_4g=False)
    spec_4 = bridge_4.build_qemu_command(allow_4g=True)
    assert spec_4.vm_ram_mb == 2048
    assert spec_4.warnings


def test_osx_kvm_qmp_hibernate_and_fallback_and_resume() -> None:
    bridge, runner, fs, qmp = _setup_kvm("8G")
    saved, note = bridge.hibernate(tag="kite-idle")
    assert saved is True
    assert note is None
    assert "kite-idle" in qmp.snapshots
    assert fs.exists(f"{bridge.runtime_dir}/kite-idle.state")
    assert [c[0] for c in qmp.commands] == ["connect", "qmp_capabilities", "stop", "savevm", "quit", "close"]

    spec_resumed = bridge.resume(tag="kite-idle")
    assert "-loadvm" in spec_resumed.qemu_argv
    assert "kite-idle" in spec_resumed.qemu_argv
    assert any(c.kind == "spawn" for c in runner.invocations)

    # vhost-user-fs savevm blocker fallback
    qmp_fail = FakeQmpClient(fail_on={"savevm": "vhost-user-fs blocks migration"})
    bridge_fail = OsxKvmBridge(
        runner=runner,
        probe=bridge.probe,
        fs=fs,
        hw_reader=bridge.hw_reader,
        qmp_client=qmp_fail,
        config=bridge.config,
    )
    saved2, note2 = bridge_fail.hibernate()
    assert saved2 is False
    assert note2 is not None and "savevm failed" in note2
    assert any(c[0] == "system_powerdown" for c in qmp_fail.commands)
    assert any(c[0] == "quit" for c in qmp_fail.commands)


def test_osx_kvm_quotes_app_target_with_spaces_and_quotes() -> None:
    bridge, _, _, _ = _setup_kvm("8G")
    spec = bridge.build_qemu_command(app_target="It's My App")
    assert spec.bridge_argv[-1] == "open -a 'It'\"'\"'s My App'"
