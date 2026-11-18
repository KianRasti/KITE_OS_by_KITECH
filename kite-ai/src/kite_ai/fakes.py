"""Deterministic in-memory fakes for Kite AI unit and cross-module E2E testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


class InMemoryFileWatcher:
    """Deterministic FileWatcher test double."""

    def __init__(self, initial_events: Sequence[str] = ()) -> None:
        self.watched: list[str] = []
        self.queued_events: list[str] = list(initial_events)

    def watch_paths(self, paths: Sequence[str]) -> None:
        self.watched = list(paths)

    def push_event(self, path: str) -> None:
        self.queued_events.append(path)

    def poll_events(self) -> list[str]:
        events = list(self.queued_events)
        self.queued_events.clear()
        return events


class InMemorySecretStore:
    """Deterministic keyring test double."""

    def __init__(self, initial: Mapping[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = dict(initial or {})

    def get_secret(self, name: str) -> str | None:
        val = self._secrets.get(name)
        return val if val else None

    def set_secret(self, name: str, value: str) -> None:
        self._secrets[name] = value

    def delete_secret(self, name: str) -> None:
        self._secrets.pop(name, None)


@dataclass
class RecordedHttpRequest:
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]


class FakeHttpClient:
    """Deterministic HTTP client test double recording requests and returning canned JSON."""

    def __init__(
        self,
        responses: Sequence[tuple[int, dict[str, Any]]] = (),
        *,
        default_status: int = 200,
        default_body: dict[str, Any] | None = None,
    ) -> None:
        self._queue: list[tuple[int, dict[str, Any]]] = list(responses)
        self.default_status = default_status
        self.default_body = default_body or {
            "groups": [{"title": "Local Matches", "items": [{"id": "F1", "why": "Relevant match"}]}],
            "action": None,
        }
        self.requests: list[RecordedHttpRequest] = []

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float = 15.0,
    ) -> tuple[int, dict[str, Any]]:
        self.requests.append(
            RecordedHttpRequest(
                url=url,
                headers=dict(headers),
                payload=dict(payload),
            )
        )
        if self._queue:
            return self._queue.pop(0)
        return self.default_status, dict(self.default_body)


@dataclass
class FakeClock:
    """Deterministic clock test double."""

    epoch_sec: int = 1_763_448_000
    mono_ms: float = 1000.0
    step_ms: float = 1.5
    calls: list[str] = field(default_factory=list)

    def now_epoch(self) -> int:
        self.calls.append("now_epoch")
        return self.epoch_sec

    def monotonic_ms(self) -> float:
        self.calls.append("monotonic_ms")
        val = self.mono_ms
        self.mono_ms += self.step_ms
        return val
