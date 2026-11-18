"""Typed data models for Kite AI local mining, indexing, compression, and BYOK routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PlatformBadge = Literal["[Doc]", "[Code]", "[Win]", "[Android]", "[macOS]"]
ProviderName = Literal["offline", "gemini", "openai", "anthropic", "groq", "openrouter"]


@dataclass(frozen=True)
class FileRecord:
    """Indexed file metadata and local mining artifacts."""

    abs_path: str
    inode: int
    mtime_ns: int
    size_bytes: int
    platform_badge: PlatformBadge
    simhash64: int
    fingerprint_25w: str
    headings: str = ""
    file_name: str = ""
    file_id: int | None = None
    canonical_file_id: int | None = None


@dataclass(frozen=True)
class SearchHit:
    """Ranked search hit returned by SQLite FTS5 hybrid retrieval."""

    file_id: int
    abs_path: str
    file_name: str
    mtime_ns: int
    size_bytes: int
    platform_badge: str
    simhash64: int
    canonical_file_id: int | None
    fingerprint_25w: str
    headings: str
    bm25_score: float
    confidence: float
    duplicate_count: int = 1


@dataclass(frozen=True)
class TokenBudget:
    """Clamped token budget enforcing sub-400 default cloud cap."""

    max_input_tokens: int = 400
    max_output_tokens: int = 220

    def __post_init__(self) -> None:
        clamped_in = max(150, min(800, int(self.max_input_tokens)))
        object.__setattr__(self, "max_input_tokens", clamped_in)
        object.__setattr__(self, "max_output_tokens", max(64, int(self.max_output_tokens)))


@dataclass(frozen=True)
class ProviderConfig:
    """BYOK cloud provider selection and endpoint configuration."""

    provider: ProviderName = "offline"
    model: str = "gemini-2.5-flash"
    secret_key_name: str = "kite-ai-api-key"
    endpoint_override: str | None = None
    tier0_threshold: float = 0.72
    token_budget: TokenBudget = field(default_factory=TokenBudget)


@dataclass(frozen=True)
class SearchGroupItem:
    """Expanded search result item with clickable KITE_OS URIs."""

    alias_id: str
    abs_path: str
    file_name: str
    platform_badge: str
    why: str
    kite_uri: str
    file_uri: str


@dataclass(frozen=True)
class SearchGroup:
    """Categorized result group returned to AI Spotlight UI."""

    title: str
    items: tuple[SearchGroupItem, ...] = ()


@dataclass(frozen=True)
class QueryResponse:
    """Final structured response from QueryRouter."""

    query: str
    tier: Literal["tier0_local", "tier1_cloud", "tier1_cached"]
    provider: str
    tokens_used: int
    estimated_input_tokens: int
    latency_ms: float
    groups: tuple[SearchGroup, ...] = ()
    action: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ToolCallResult:
    """Result returned by sandboxed OS tools."""

    tool_name: str
    ok: bool
    tokens_cost: int
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class IndexTelemetry:
    """Summary metrics surfaced to Settings Bento Grid and CLI status."""

    total_files: int
    canonical_files: int
    duplicate_collapsed: int
    max_mtime_ns: int
    cache_entries: int
    db_size_bytes: int
