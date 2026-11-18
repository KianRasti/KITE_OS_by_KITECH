"""Static prompt-cache prefix & strict compact JSON response schema validator."""

from __future__ import annotations

import json
from typing import Any

from .. import MAX_WHY_WORDS

# Static system prompt kept byte-identical at the start of every payload for prefix caching.
SYSTEM_PREFIX = (
    "You are KiteAI, the OS file & system intelligence for KITE_OS. "
    "Return ONLY valid JSON matching schema: "
    '{"groups":[{"title":str,"items":[{"id":str,"why":str}]}],"action":str|null}'
)


class SchemaValidationError(ValueError):
    """Raised when a cloud BYOK response violates the compact JSON schema."""


def parse_strict_response(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize cloud JSON payload into canonical compact dict."""
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"Invalid JSON from provider: {exc}") from exc
    elif isinstance(raw, dict):
        data = raw
    else:
        raise SchemaValidationError("Provider response must be JSON object or string.")

    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise SchemaValidationError("Response missing required 'groups' list.")

    normalized_groups: list[dict[str, Any]] = []
    for grp in data["groups"]:
        if not isinstance(grp, dict) or "title" not in grp or not isinstance(grp.get("items"), list):
            raise SchemaValidationError("Each group must have 'title' and 'items' list.")
        items: list[dict[str, str]] = []
        for item in grp["items"]:
            if not isinstance(item, dict) or not item.get("id"):
                raise SchemaValidationError("Each group item must include non-empty 'id'.")
            why = " ".join(str(item.get("why", "")).split()[:MAX_WHY_WORDS])
            items.append({"id": str(item["id"]).strip(), "why": why or "Relevant file"})
        normalized_groups.append({"title": str(grp["title"]), "items": items})

    action_val = data.get("action")
    if action_val is not None and not isinstance(action_val, str):
        raise SchemaValidationError("'action' must be string or null.")

    return {"groups": normalized_groups, "action": action_val}
