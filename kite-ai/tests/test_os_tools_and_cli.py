"""Unit tests for Sandboxed OS Tools, CLI/IPC handler, and systemd/install scripts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from kite_ai.cli import handle_ipc_request, main
from kite_ai.fakes import FakeClock, FakeHttpClient, InMemorySecretStore
from kite_ai.index.store import IndexStore
from kite_ai.providers.router import QueryRouter
from kite_ai.tools.os_tools import OsToolbox

KITE_AI_DIR = Path(__file__).resolve().parent.parent


def test_os_tools_search_and_inspect_head_and_privacy_block(tmp_path: Path) -> None:
    doc = tmp_path / "notes.md"
    doc.write_text("# Heading One\n" + "\n".join(f"Line {i}" for i in range(1, 40)), encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=123\n", encoding="utf-8")

    with IndexStore(tmp_path / "db.sqlite") as store:
        store.index_directory(tmp_path)
        tb = OsToolbox(store)

        s_res = tb.search_local_index("Heading One")
        assert s_res.ok is True
        assert s_res.data["count"] == 1
        assert 0 <= s_res.tokens_cost <= 250

        h_res = tb.inspect_file_head(str(doc))
        assert h_res.ok is True
        assert len(h_res.data["head_lines"]) == 25
        assert 80 <= h_res.tokens_cost <= 150

        blocked = tb.inspect_file_head(str(env_file))
        assert blocked.ok is False
        assert "privacy" in (blocked.error or "").lower()


def test_os_tools_apply_setting_enforces_hw_profile_clamps(tmp_path: Path) -> None:
    hw_4g = tmp_path / "hw4g.json"
    hw_4g.write_text(json.dumps({"memory": {"tier": "4G"}, "power": {"source": "AC"}}), encoding="utf-8")
    settings_json = tmp_path / "settings.json"

    with IndexStore(":memory:") as store:
        tb = OsToolbox(store, hw_profile_path=hw_4g, settings_path=settings_json)
        res = tb.apply_os_setting({"blur_passes": 2, "blur_size": 6, "taskbar_alignment": "left"})
        assert res.ok is True
        assert res.data["applied"]["blur_passes"] == 0
        assert res.data["applied"]["blur_size"] == 0
        assert res.data["applied"]["taskbar_alignment"] == "left"
        assert 40 <= res.tokens_cost <= 90

        bad_dxvk = tb.apply_os_setting({"dxvk_version": "2.3"})
        assert bad_dxvk.ok is False


def test_os_tools_diagnose_runtime_catches_dxvk_2x_and_disabled_wined3d(tmp_path: Path) -> None:
    prefix = tmp_path / "wine-prefix"
    prefix.mkdir()
    (prefix / ".kitebridge-manifest.json").write_text(
        json.dumps({"dxvk_version": "2.3", "wined3d_dx12": False}),
        encoding="utf-8",
    )
    hw_8g = tmp_path / "hw8g.json"
    hw_8g.write_text(
        json.dumps({"memory": {"tier": "8G"}, "power": {"source": "AC"}, "subsystems": {"wine": {"dxvk_version": "1.10.3"}}}),
        encoding="utf-8",
    )

    with IndexStore(":memory:") as store:
        tb = OsToolbox(store, hw_profile_path=hw_8g, wine_prefix_path=prefix)
        diag = tb.diagnose_runtime("wine")
        assert diag.ok is True
        assert diag.data["healthy"] is False
        assert len(diag.data["findings"]) == 2
        assert diag.data["driver_pins"]["MESA_LOADER_DRIVER_OVERRIDE"] == "crocus"
        assert diag.data["driver_pins"]["LIBVA_DRIVER_NAME"] == "i965"
        assert diag.data["driver_pins"]["DXVK_VER"] == "1.10.3"


def test_cli_index_query_status_and_ipc_handler(tmp_path: Path, capsys) -> None:
    sample = tmp_path / "workspace"
    sample.mkdir()
    (sample / "capstone.md").write_text("# Capstone\nGreenhouse controller\n", encoding="utf-8")
    db = tmp_path / "kite-ai.db"

    assert main(["--db", str(db), "index", str(sample)]) == 0
    idx_out = json.loads(capsys.readouterr().out)
    assert idx_out["ok"] is True and idx_out["stats"]["indexed"] == 1

    assert main(["--db", str(db), "status"]) == 0
    st_out = json.loads(capsys.readouterr().out)
    assert st_out["telemetry"]["total_files"] == 1

    assert main(["--db", str(db), "query", "capstone"]) == 0
    q_out = json.loads(capsys.readouterr().out)
    assert q_out["tier"] == "tier0_local" and q_out["tokens_used"] == 0

    with IndexStore(db) as store:
        router = QueryRouter(store, secret_store=InMemorySecretStore(), http_client=FakeHttpClient(), clock=FakeClock())
        ipc = handle_ipc_request(json.dumps({"op": "query", "q": "greenhouse"}), store=store, router=router, toolbox=OsToolbox(store))
        assert ipc["ok"] is True


def test_systemd_socket_timer_and_install_sh() -> None:
    sock = (KITE_AI_DIR / "systemd" / "kite-aid.socket").read_text(encoding="utf-8")
    svc = (KITE_AI_DIR / "systemd" / "kite-aid.service").read_text(encoding="utf-8")
    timer = (KITE_AI_DIR / "systemd" / "kite-index.timer").read_text(encoding="utf-8")
    idx_svc = (KITE_AI_DIR / "systemd" / "kite-index.service").read_text(encoding="utf-8")

    assert "ListenStream=/run/kite-os/kite-ai.sock" in sock
    assert "StandardInput=socket" in svc
    assert "[Timer]" in timer
    assert "ionice -c 3" in idx_svc and "IOSchedulingClass=idle" in idx_svc

    install_sh = KITE_AI_DIR / "install.sh"
    assert b"\r\n" not in install_sh.read_bytes()
    bash = r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("bash")
    if bash and Path(bash).exists():
        r = subprocess.run([bash, "-n", str(install_sh)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r2 = subprocess.run([bash, str(install_sh), "--dry-run"], capture_output=True, text=True)
        assert r2.returncode == 0 and "dry-run" in r2.stdout
