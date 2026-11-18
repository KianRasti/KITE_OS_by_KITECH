"""Path-to-ID (F1..Fn) compressor & URI expander (kite://open?path=... and file:///...)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from urllib.parse import quote

from .. import MAX_ALIAS_CANDIDATES
from ..models import SearchGroup, SearchGroupItem, SearchHit, TokenBudget


def estimate_tokens(text: str) -> int:
    """Fast deterministic token estimator (~4 chars/token + boundary fudge)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def build_kite_uri(abs_path: str) -> str:
    norm = abs_path.replace("\\", "/")
    return f"kite://open?path={quote(norm, safe='/')}"


def build_file_uri(abs_path: str) -> str:
    norm = abs_path.replace("\\", "/")
    if not norm.startswith("/"):
        norm = "/" + norm
    return f"file://{quote(norm, safe='/:')}"


@dataclass(frozen=True)
class AliasTable:
    """Bidirectional alias table mapping F1..Fn to SearchHits."""

    by_id: dict[str, SearchHit]
    compact_index: str
    estimated_tokens: int


class PathAliaser:
    """Compresses candidate SearchHits into compact F1..F10 lines within TokenBudget."""

    def __init__(self, *, max_candidates: int = MAX_ALIAS_CANDIDATES) -> None:
        self.max_candidates = max(1, min(MAX_ALIAS_CANDIDATES, max_candidates))

    @staticmethod
    def _format_date(mtime_ns: int) -> str:
        if mtime_ns <= 0:
            return "1970-01-01"
        sec = mtime_ns / 1_000_000_000.0
        return datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%d")

    def compress(
        self,
        query: str,
        hits: Sequence[SearchHit],
        *,
        system_prefix: str = "",
        budget: TokenBudget | None = None,
    ) -> AliasTable:
        """Map top deduplicated hits to F1..F10 and keep total prompt within budget."""
        active_budget = budget or TokenBudget()
        prefix_tokens = estimate_tokens(system_prefix) + estimate_tokens(f"Q: {query}\nINDEX:\n")
        remaining = max(40, active_budget.max_input_tokens - prefix_tokens)

        by_id: dict[str, SearchHit] = {}
        lines: list[str] = []
        used = 0

        for idx, hit in enumerate(hits[: self.max_candidates], start=1):
            alias = f"F{idx}"
            date_str = self._format_date(hit.mtime_ns)
            fp = ",".join([w for w in hit.fingerprint_25w.split(",") if w][:12])
            line = f"{alias}|{hit.file_name}|{date_str}|{hit.platform_badge}|{fp}"
            line_toks = estimate_tokens(line + "\n")
            if lines and (used + line_toks) > remaining:
                break
            by_id[alias] = hit
            lines.append(line)
            used += line_toks

        compact = "\n".join(lines)
        return AliasTable(
            by_id=by_id,
            compact_index=compact,
            estimated_tokens=prefix_tokens + used,
        )

    def expand_groups(
        self,
        raw_groups: Sequence[dict[str, object]],
        table: AliasTable,
    ) -> tuple[SearchGroup, ...]:
        """Rehydrate alias IDs into clickable kite://open and file:/// URI cards."""
        expanded: list[SearchGroup] = []
        for grp in raw_groups:
            title = str(grp.get("title") or "Results")
            raw_items = grp.get("items") or []
            if not isinstance(raw_items, list):
                continue
            out_items: list[SearchGroupItem] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                alias = str(item.get("id") or "").strip()
                hit = table.by_id.get(alias)
                if hit is None:
                    continue
                why_words = str(item.get("why") or "Local index match").split()[:12]
                out_items.append(
                    SearchGroupItem(
                        alias_id=alias,
                        abs_path=hit.abs_path,
                        file_name=hit.file_name,
                        platform_badge=hit.platform_badge,
                        why=" ".join(why_words),
                        kite_uri=build_kite_uri(hit.abs_path),
                        file_uri=build_file_uri(hit.abs_path),
                    )
                )
            if out_items:
                expanded.append(SearchGroup(title=title, items=tuple(out_items)))
        return tuple(expanded)
