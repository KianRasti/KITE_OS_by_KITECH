"""Unit tests for PathAliaser, strict schema, and two-tier BYOK QueryRouter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kite_ai.compress.aliaser import PathAliaser, build_file_uri, build_kite_uri
from kite_ai.fakes import FakeClock, FakeHttpClient, InMemorySecretStore
from kite_ai.index.store import IndexStore
from kite_ai.models import FileRecord, ProviderConfig, TokenBudget
from kite_ai.providers.router import QueryRouter
from kite_ai.providers.schema import SYSTEM_PREFIX, SchemaValidationError, parse_strict_response


def _seed_store(store: IndexStore, count: int = 12) -> None:
    for i in range(1, count + 1):
        store.upsert_record(
            FileRecord(
                abs_path=f"/home/kite/Documents/University/Capstone/Greenhouse_Spec_v{i}.md",
                file_name=f"Greenhouse_Spec_v{i}.md",
                headings="Capstone Greenhouse Spec",
                inode=100 + i,
                mtime_ns=1_763_000_000_000_000_000 + i * 1_000_000_000,
                size_bytes=2048,
                platform_badge="[Doc]",
                simhash64=i * 1000000007,
                canonical_file_id=i,
                fingerprint_25w="capstone,greenhouse,esp32,sensor,pid,fan,pwm,telemetry",
            )
        )


def test_token_budget_clamps_to_150_800_with_400_default() -> None:
    assert TokenBudget().max_input_tokens == 400
    assert TokenBudget(max_input_tokens=50).max_input_tokens == 150
    assert TokenBudget(max_input_tokens=2000).max_input_tokens == 800


def test_path_aliaser_caps_at_10_candidates_and_sub_400_tokens() -> None:
    with IndexStore(":memory:") as store:
        _seed_store(store, count=15)
        hits = store.search("greenhouse capstone", limit=15, collapse_duplicates=False)
        table = PathAliaser().compress(
            "find my university capstone greenhouse files",
            hits,
            system_prefix=SYSTEM_PREFIX,
            budget=TokenBudget(max_input_tokens=400),
        )
        assert 1 <= len(table.by_id) <= 10
        assert table.estimated_tokens <= 400
        assert "/home/kite/Documents" not in table.compact_index
        assert "F1|" in table.compact_index


def test_uri_builders_and_expansion() -> None:
    assert build_kite_uri("/home/kite/a b.pdf") == "kite://open?path=/home/kite/a%20b.pdf"
    assert build_file_uri("/home/kite/a b.pdf") == "file:///home/kite/a%20b.pdf"


def test_strict_schema_truncates_why_to_12_words_and_rejects_invalid() -> None:
    parsed = parse_strict_response({
        "groups": [{"title": "Specs", "items": [{"id": "F1", "why": "one two three four five six seven eight nine ten eleven twelve thirteen"}]}],
        "action": None,
    })
    assert len(parsed["groups"][0]["items"][0]["why"].split()) == 12
    with pytest.raises(SchemaValidationError):
        parse_strict_response("not valid json")


def test_router_tier0_zero_tokens_when_offline_or_4g_battery(tmp_path: Path) -> None:
    with IndexStore(":memory:") as store:
        _seed_store(store, count=3)
        http = FakeHttpClient()
        secrets = InMemorySecretStore()
        router = QueryRouter(store, secret_store=secrets, http_client=http, clock=FakeClock())
        resp = router.query("greenhouse capstone")
        assert resp.tier == "tier0_local"
        assert resp.tokens_used == 0
        assert len(http.requests) == 0
        assert resp.groups and resp.groups[0].items[0].kite_uri.startswith("kite://open?path=")

        # Even with API key + force_cloud=True, 4G Battery forces Tier 0 zero-token policy
        hw_prof = tmp_path / "hw-profile.json"
        hw_prof.write_text(json.dumps({"memory": {"tier": "4G"}, "power": {"source": "Battery"}}), encoding="utf-8")
        secrets.set_secret("kite-ai-api-key", "sk-test")
        router_4g = QueryRouter(
            store,
            secret_store=secrets,
            http_client=http,
            clock=FakeClock(),
            config=ProviderConfig(provider="gemini"),
            hw_profile_path=hw_prof,
        )
        resp_4g = router_4g.query("greenhouse capstone", force_cloud=True)
        assert resp_4g.tier == "tier0_local"
        assert resp_4g.tokens_used == 0
        assert resp_4g.fallback_reason == "4G_BATTERY_TIER0_POLICY"
        assert len(http.requests) == 0


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic", "groq", "openrouter"])
def test_router_tier1_byok_providers_and_cache_hit(provider: str) -> None:
    with IndexStore(":memory:") as store:
        _seed_store(store, count=4)
        canned = {"groups": [{"title": "Capstone", "items": [{"id": "F1", "why": "Primary greenhouse spec"}]}], "action": None}
        if provider == "gemini":
            body = {"candidates": [{"content": {"parts": [{"text": json.dumps(canned)}]}}]}
        elif provider == "anthropic":
            body = {"content": [{"text": json.dumps(canned)}]}
        else:
            body = {"choices": [{"message": {"content": json.dumps(canned)}}]}

        http = FakeHttpClient(responses=[(200, body)])
        secrets = InMemorySecretStore({"kite-ai-api-key": "test-secret"})
        router = QueryRouter(
            store,
            secret_store=secrets,
            http_client=http,
            clock=FakeClock(),
            config=ProviderConfig(provider=provider, token_budget=TokenBudget(max_input_tokens=400)),  # type: ignore[arg-type]
        )

        r1 = router.query("greenhouse capstone", force_cloud=True)
        assert r1.tier == "tier1_cloud"
        assert r1.estimated_input_tokens <= 400
        assert len(http.requests) == 1
        assert r1.groups[0].items[0].kite_uri.startswith("kite://open?path=")

        # Second identical query hits query_cache with 0 tokens and no HTTP call
        r2 = router.query("greenhouse capstone", force_cloud=True)
        assert r2.tier == "tier1_cached"
        assert r2.tokens_used == 0
        assert len(http.requests) == 1
