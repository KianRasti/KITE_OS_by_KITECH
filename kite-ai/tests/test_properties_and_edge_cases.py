"""Property and boundary tests for Kite AI (token budgets, SimHash properties, and error fallbacks)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kite_ai.compress.aliaser import PathAliaser, estimate_tokens
from kite_ai.fakes import FakeClock, FakeHttpClient, InMemoryFileWatcher, InMemorySecretStore
from kite_ai.index.store import IndexStore
from kite_ai.mining.simhash import compute_simhash64, hamming_distance64
from kite_ai.mining.textrank import extract_fingerprint_25w
from kite_ai.models import FileRecord, ProviderConfig, SearchHit, TokenBudget
from kite_ai.providers.router import QueryRouter
from kite_ai.providers.schema import SYSTEM_PREFIX
from kite_ai.tools.os_tools import OsToolbox


@pytest.mark.parametrize("budget_val", [50, 150, 250, 400, 600, 800, 1200])
def test_property_aliaser_always_respects_clamped_token_budget(budget_val: int) -> None:
    budget = TokenBudget(max_input_tokens=budget_val)
    hits = [
        SearchHit(
            file_id=i,
            abs_path=f"/home/kite/very/deep/nested/folder/structure/project_{i}/Document_Draft_Number_{i}.md",
            file_name=f"Document_Draft_Number_{i}.md",
            mtime_ns=1_763_000_000_000_000_000 + i,
            size_bytes=4096,
            platform_badge="[Doc]",
            simhash64=i * 999999937,
            canonical_file_id=i,
            fingerprint_25w=",".join(f"term{j}" for j in range(1, 26)),
            headings="Heading",
            bm25_score=-2.5,
            confidence=0.6,
        )
        for i in range(1, 15)
    ]
    table = PathAliaser().compress("find my project documents", hits, system_prefix=SYSTEM_PREFIX, budget=budget)
    assert table.estimated_tokens <= budget.max_input_tokens
    assert 1 <= len(table.by_id) <= 10


@pytest.mark.parametrize("seed_idx", range(1, 6))
def test_property_simhash_reflexive_symmetric_and_bounded(seed_idx: int) -> None:
    a = f"kite os haswell folio 9480m intel crocus i965 dxvk 1.10.3 seed {seed_idx}"
    b = f"waydroid android multi window binder_linux cgroup freeze seed {seed_idx * 17}"
    ha = compute_simhash64(a)
    hb = compute_simhash64(b)
    assert hamming_distance64(ha, ha) == 0
    assert hamming_distance64(ha, hb) == hamming_distance64(hb, ha)
    assert 0 <= hamming_distance64(ha, hb) <= 64


@pytest.mark.parametrize("http_status", [401, 429, 500, 503])
def test_router_cloud_http_errors_fall_back_gracefully_to_tier0(http_status: int) -> None:
    with IndexStore(":memory:") as store:
        store.upsert_record(
            FileRecord(
                abs_path="/home/kite/notes.md",
                file_name="notes.md",
                headings="Notes",
                inode=1,
                mtime_ns=100,
                size_bytes=64,
                platform_badge="[Doc]",
                simhash64=12345,
                canonical_file_id=1,
                fingerprint_25w="notes,greenhouse,capstone",
            )
        )
        http = FakeHttpClient(responses=[(http_status, {"error": "upstream error"})])
        secrets = InMemorySecretStore({"kite-ai-api-key": "sk-test"})
        router = QueryRouter(
            store,
            secret_store=secrets,
            http_client=http,
            clock=FakeClock(),
            config=ProviderConfig(provider="openai"),
        )
        resp = router.query("greenhouse", force_cloud=True)
        assert resp.tier == "tier0_local"
        assert resp.tokens_used == 0
        assert resp.fallback_reason == f"CLOUD_HTTP_{http_status}"


def test_router_invalid_cloud_schema_falls_back_to_tier0() -> None:
    with IndexStore(":memory:") as store:
        store.upsert_record(
            FileRecord(
                abs_path="/home/kite/notes.md",
                file_name="notes.md",
                headings="Notes",
                inode=1,
                mtime_ns=100,
                size_bytes=64,
                platform_badge="[Doc]",
                simhash64=12345,
                canonical_file_id=1,
                fingerprint_25w="notes,greenhouse",
            )
        )
        http = FakeHttpClient(responses=[(200, {"choices": [{"message": {"content": "NOT JSON"}}]})])
        secrets = InMemorySecretStore({"kite-ai-api-key": "sk-test"})
        router = QueryRouter(
            store,
            secret_store=secrets,
            http_client=http,
            clock=FakeClock(),
            config=ProviderConfig(provider="openai"),
        )
        resp = router.query("greenhouse", force_cloud=True)
        assert resp.tier == "tier0_local"
        assert resp.fallback_reason == "CLOUD_SCHEMA_INVALID"


def test_os_tools_8g_battery_clamps_blur_passes_to_1(tmp_path: Path) -> None:
    hw_8g_bat = tmp_path / "hw.json"
    hw_8g_bat.write_text(json.dumps({"memory": {"tier": "8G"}, "power": {"source": "Battery"}}), encoding="utf-8")
    with IndexStore(":memory:") as store:
        tb = OsToolbox(store, hw_profile_path=hw_8g_bat)
        res = tb.apply_os_setting({"blur_passes": 2, "blur_size": 6})
        assert res.ok is True
        assert res.data["applied"]["blur_passes"] == 1
        assert res.data["applied"]["blur_size"] == 4


def test_inmemory_watcher_and_empty_textrank_and_token_estimator() -> None:
    w = InMemoryFileWatcher(["/home/kite/a.md"])
    w.watch_paths(["/home/kite"])
    w.push_event("/home/kite/b.md")
    assert w.poll_events() == ["/home/kite/a.md", "/home/kite/b.md"]
    assert w.poll_events() == []
    assert extract_fingerprint_25w("") == ""
    assert estimate_tokens("") == 0
