"""Two-tier QueryRouter: Tier 0 local fast path (<10ms, 0 tokens) + Tier 1 BYOK router."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..abstractions import Clock, HttpClient, SecretStore, SystemClock
from ..compress.aliaser import PathAliaser, build_file_uri, build_kite_uri
from ..index.store import IndexStore, compute_query_hash
from ..models import ProviderConfig, QueryResponse, SearchGroup, SearchGroupItem, SearchHit
from .schema import SYSTEM_PREFIX, SchemaValidationError, parse_strict_response

_DEFAULT_ENDPOINTS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


class QueryRouter:
    """Executes deterministic Tier 0 local searches and optional <400-token BYOK calls."""

    def __init__(
        self,
        store: IndexStore,
        *,
        secret_store: SecretStore,
        http_client: HttpClient,
        clock: Clock | None = None,
        config: ProviderConfig | None = None,
        hw_profile_path: str | Path = "/run/kite-os/hw-profile.json",
    ) -> None:
        self.store = store
        self.secret_store = secret_store
        self.http_client = http_client
        self.clock = clock or SystemClock()
        self.config = config or ProviderConfig()
        self.hw_profile_path = Path(hw_profile_path)
        self.aliaser = PathAliaser()

    def _is_4g_battery_forced_tier0(self) -> bool:
        if not self.hw_profile_path.is_file():
            return False
        try:
            data = json.loads(self.hw_profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        tier = str((data.get("memory") or {}).get("tier", ""))
        source = str((data.get("power") or {}).get("source", ""))
        kite_ai_cfg = (data.get("subsystems") or {}).get("kite_ai") or {}
        if kite_ai_cfg.get("default_tier0_only") is True:
            return True
        return tier == "4G" and source == "Battery"

    def _local_tier0_groups(self, hits: list[SearchHit]) -> tuple[SearchGroup, ...]:
        items: list[SearchGroupItem] = []
        for idx, hit in enumerate(hits, start=1):
            dup_note = f" ({hit.duplicate_count} drafts collapsed)" if hit.duplicate_count > 1 else ""
            kw_preview = ", ".join(hit.fingerprint_25w.split(",")[:4])
            why = f"Local BM25 match ({kw_preview}){dup_note}" if kw_preview else f"Local BM25 match{dup_note}"
            items.append(
                SearchGroupItem(
                    alias_id=f"F{idx}",
                    abs_path=hit.abs_path,
                    file_name=hit.file_name,
                    platform_badge=hit.platform_badge,
                    why=" ".join(why.split()[:12]),
                    kite_uri=build_kite_uri(hit.abs_path),
                    file_uri=build_file_uri(hit.abs_path),
                )
            )
        if not items:
            return ()
        return (SearchGroup(title="Local Fast Path", items=tuple(items)),)

    def _build_provider_request(
        self,
        provider: str,
        api_key: str,
        user_payload: str,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url_tpl = self.config.endpoint_override or _DEFAULT_ENDPOINTS[provider]
        url = url_tpl.format(model=self.config.model)

        if provider == "gemini":
            headers = {"x-goog-api-key": api_key}
            payload: dict[str, Any] = {
                "system_instruction": {"parts": [{"text": SYSTEM_PREFIX}]},
                "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
                "generationConfig": {
                    "maxOutputTokens": self.config.token_budget.max_output_tokens,
                    "responseMimeType": "application/json",
                },
            }
            return url, headers, payload

        if provider == "anthropic":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
            payload = {
                "model": self.config.model,
                "max_tokens": self.config.token_budget.max_output_tokens,
                "system": SYSTEM_PREFIX,
                "messages": [{"role": "user", "content": user_payload}],
            }
            return url, headers, payload

        # OpenAI / Groq / OpenRouter compatible
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.token_budget.max_output_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PREFIX},
                {"role": "user", "content": user_payload},
            ],
        }
        return url, headers, payload

    @staticmethod
    def _extract_provider_body(provider: str, resp_json: dict[str, Any]) -> str | dict[str, Any]:
        if "groups" in resp_json:
            return resp_json
        if provider == "gemini":
            cands = resp_json.get("candidates") or []
            if cands:
                parts = ((cands[0].get("content") or {}).get("parts")) or []
                if parts and "text" in parts[0]:
                    return str(parts[0]["text"])
        elif provider == "anthropic":
            content = resp_json.get("content") or []
            if content and "text" in content[0]:
                return str(content[0]["text"])
        else:
            choices = resp_json.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                if "content" in msg:
                    return str(msg["content"])
        return resp_json

    def query(
        self,
        query_text: str,
        *,
        force_cloud: bool = False,
        limit: int = 10,
    ) -> QueryResponse:
        """Execute Tier 0 local search or Tier 1 compressed BYOK cloud synthesis."""
        t0 = self.clock.monotonic_ms()
        hits = self.store.search(query_text, limit=limit, collapse_duplicates=True)
        top_conf = hits[0].confidence if hits else 0.0

        provider = self.config.provider
        api_key = self.secret_store.get_secret(self.config.secret_key_name) if provider != "offline" else None
        forced_4g_tier0 = self._is_4g_battery_forced_tier0()

        use_tier0 = (
            provider == "offline"
            or api_key is None
            or forced_4g_tier0
            or (not force_cloud and hits and top_conf >= self.config.tier0_threshold)
        )

        if use_tier0:
            reason = None
            if forced_4g_tier0:
                reason = "4G_BATTERY_TIER0_POLICY"
            elif provider == "offline" or api_key is None:
                reason = "OFFLINE_OR_NO_API_KEY"
            groups = self._local_tier0_groups(hits)
            elapsed = max(0.01, self.clock.monotonic_ms() - t0)
            return QueryResponse(
                query=query_text,
                tier="tier0_local",
                provider="local-fts5",
                tokens_used=0,
                estimated_input_tokens=0,
                latency_ms=round(elapsed, 3),
                groups=groups,
                action=None,
                fallback_reason=reason,
            )

        table = self.aliaser.compress(
            query_text,
            hits,
            system_prefix=SYSTEM_PREFIX,
            budget=self.config.token_budget,
        )
        q_hash = compute_query_hash(
            query_text,
            provider=provider,
            max_tokens=self.config.token_budget.max_input_tokens,
        )
        cached = self.store.get_cached_query(q_hash)
        if cached is not None:
            parsed_cached = parse_strict_response(cached)
            groups = self.aliaser.expand_groups(parsed_cached["groups"], table)
            elapsed = max(0.01, self.clock.monotonic_ms() - t0)
            return QueryResponse(
                query=query_text,
                tier="tier1_cached",
                provider=provider,
                tokens_used=0,
                estimated_input_tokens=table.estimated_tokens,
                latency_ms=round(elapsed, 3),
                groups=groups,
                action=parsed_cached.get("action"),
            )

        user_payload = f"Q: {query_text}\nINDEX:\n{table.compact_index}"
        url, headers, payload = self._build_provider_request(provider, api_key, user_payload)
        status, resp_json = self.http_client.post_json(url, headers=headers, payload=payload)

        if status >= 400:
            elapsed = max(0.01, self.clock.monotonic_ms() - t0)
            return QueryResponse(
                query=query_text,
                tier="tier0_local",
                provider="local-fts5",
                tokens_used=0,
                estimated_input_tokens=table.estimated_tokens,
                latency_ms=round(elapsed, 3),
                groups=self._local_tier0_groups(hits),
                fallback_reason=f"CLOUD_HTTP_{status}",
            )

        try:
            body = self._extract_provider_body(provider, resp_json)
            parsed = parse_strict_response(body)
        except SchemaValidationError:
            elapsed = max(0.01, self.clock.monotonic_ms() - t0)
            return QueryResponse(
                query=query_text,
                tier="tier0_local",
                provider="local-fts5",
                tokens_used=0,
                estimated_input_tokens=table.estimated_tokens,
                latency_ms=round(elapsed, 3),
                groups=self._local_tier0_groups(hits),
                fallback_reason="CLOUD_SCHEMA_INVALID",
            )

        self.store.put_cached_query(q_hash, json.dumps(parsed), self.clock.now_epoch())
        groups = self.aliaser.expand_groups(parsed["groups"], table)
        elapsed = max(0.01, self.clock.monotonic_ms() - t0)
        return QueryResponse(
            query=query_text,
            tier="tier1_cloud",
            provider=provider,
            tokens_used=table.estimated_tokens + min(120, len(json.dumps(parsed)) // 4),
            estimated_input_tokens=table.estimated_tokens,
            latency_ms=round(elapsed, 3),
            groups=groups,
            action=parsed.get("action"),
        )
