"""Cross-module E2E verification for Phase 6 (Kite AI + KiteHwTune + KiteShell + ISO + Invariants)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kite_ai.fakes import FakeClock, FakeHttpClient, InMemorySecretStore
from kite_ai.index.store import IndexStore
from kite_ai.models import ProviderConfig, TokenBudget
from kite_ai.providers.router import QueryRouter
from kite_ai.tools.os_tools import OsToolbox
from kite_hw_tune.abstractions import FakeClock as HwFakeClock
from kite_hw_tune.abstractions import FakeCmdRunner, FakeEnvWriter, FakeProcFs, FakeSysFs
from kite_hw_tune.tuner import HardwareTuner

pytestmark = pytest.mark.tier1


def test_e2e_hw_tune_4g_battery_forces_kite_ai_tier0_and_static_blur(tmp_path: Path) -> None:
    prof_path = tmp_path / "hw-profile.json"
    proc_fs = FakeProcFs({"/proc/meminfo": "MemTotal:        4096000 kB\n"})
    sys_fs = FakeSysFs({
        "/sys/class/power_supply/AC/type": "Mains\n",
        "/sys/class/power_supply/AC/online": "0\n",
        "/sys/block/sda/queue/rotational": "1\n",
    })
    env_writer = FakeEnvWriter()
    tuner = HardwareTuner(
        proc_fs=proc_fs,
        sys_fs=sys_fs,
        cmd=FakeCmdRunner(),
        env_writer=env_writer,
        clock=HwFakeClock(),
    )
    res = tuner.run_hw_tune(apply_system=False, write_files=True)
    prof_dict = res.profile.to_dict()
    assert prof_dict["subsystems"]["kite_ai"]["socket_only"] is True
    assert prof_dict["subsystems"]["kite_ai"]["background_watch"] is False
    assert prof_dict["subsystems"]["kite_ai"]["default_tier0_only"] is True
    assert prof_dict["blur"]["tier"] == "static"

    prof_path.write_text(json.dumps(prof_dict), encoding="utf-8")
    doc = tmp_path / "notes.md"
    doc.write_text("# Capstone Greenhouse\nESP32 PID controller\n", encoding="utf-8")

    with IndexStore(tmp_path / "ai.db") as store:
        store.index_directory(tmp_path)
        http = FakeHttpClient()
        router = QueryRouter(
            store,
            secret_store=InMemorySecretStore({"kite-ai-api-key": "sk-live"}),
            http_client=http,
            clock=FakeClock(),
            config=ProviderConfig(provider="gemini", token_budget=TokenBudget(max_input_tokens=400)),
            hw_profile_path=prof_path,
        )
        qres = router.query("greenhouse", force_cloud=True)
        assert qres.tier == "tier0_local"
        assert qres.tokens_used == 0
        assert len(http.requests) == 0

        tb = OsToolbox(store, hw_profile_path=prof_path)
        ares = tb.apply_os_setting({"blur_passes": 2, "blur_size": 6})
        assert ares.ok is True
        assert ares.data["applied"]["blur_passes"] == 0


def test_e2e_phase6_invariants_20_of_20(repo_root: Path, python_exe: str) -> None:
    res = subprocess.run(
        [python_exe, str(repo_root / "scripts" / "check_invariants.py"), "--json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    data = json.loads(res.stdout)
    assert data["ok"] is True
    assert len(data["checks_passed"]) == 20
    assert "kite-ai:privacy:kiteignore-guardrail" in data["checks_passed"]
    assert "kite-ai:zero-daemon-ram:socket-activation" in data["checks_passed"]
    assert "kite-ai:token-budget:sub-400-cap" in data["checks_passed"]
