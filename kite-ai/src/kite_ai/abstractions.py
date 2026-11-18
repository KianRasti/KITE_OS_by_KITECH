"""Runtime-checkable OS abstraction protocols and production adapters for Kite AI."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class FileWatcher(Protocol):
    """Protocol for incremental file change event polling."""

    def poll_events(self) -> list[str]: ...

    def watch_paths(self, paths: Sequence[str]) -> None: ...


@runtime_checkable
class SecretStore(Protocol):
    """Protocol for Linux kernel keyring / libsecret API key storage."""

    def get_secret(self, name: str) -> str | None: ...

    def set_secret(self, name: str, value: str) -> None: ...

    def delete_secret(self, name: str) -> None: ...


@runtime_checkable
class HttpClient(Protocol):
    """Protocol for HTTPS JSON requests to BYOK cloud providers."""

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float = 15.0,
    ) -> tuple[int, dict[str, Any]]: ...


@runtime_checkable
class Clock(Protocol):
    """Protocol for monotonic and wall-clock timestamps."""

    def now_epoch(self) -> int: ...

    def monotonic_ms(self) -> float: ...


class SystemClock:
    """Production wall & monotonic clock."""

    def now_epoch(self) -> int:
        return int(time.time())

    def monotonic_ms(self) -> float:
        return time.monotonic() * 1000.0


class EnvSecretStore:
    """Fallback secret store reading environment or XDG keyring stub cleanly."""

    def __init__(self, *, env_prefix: str = "KITE_AI_SECRET_") -> None:
        self.env_prefix = env_prefix

    def get_secret(self, name: str) -> str | None:
        env_key = f"{self.env_prefix}{name.upper().replace('-', '_')}"
        val = os.environ.get(env_key) or os.environ.get("KITE_AI_API_KEY")
        return val.strip() if val and val.strip() else None

    def set_secret(self, name: str, value: str) -> None:
        env_key = f"{self.env_prefix}{name.upper().replace('-', '_')}"
        os.environ[env_key] = value

    def delete_secret(self, name: str) -> None:
        env_key = f"{self.env_prefix}{name.upper().replace('-', '_')}"
        os.environ.pop(env_key, None)


class UrllibHttpClient:
    """Standard-library HTTPS JSON client (zero third-party runtime dependencies)."""

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: float = 15.0,
    ) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return int(resp.status), json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = {"error": raw}
            return int(exc.code), parsed


class PollingFileWatcher:
    """Lightweight mtime-snapshot watcher without persistent inotify daemon threads."""

    def __init__(self) -> None:
        self._watched: list[Path] = []
        self._seen_mtimes: dict[str, int] = {}

    def watch_paths(self, paths: Sequence[str]) -> None:
        self._watched = [Path(p) for p in paths]

    def poll_events(self) -> list[str]:
        changed: list[str] = []
        for root in self._watched:
            if not root.exists():
                continue
            for item in root.rglob("*"):
                if not item.is_file():
                    continue
                key = str(item)
                mtime = item.stat().st_mtime_ns
                if self._seen_mtimes.get(key) != mtime:
                    self._seen_mtimes[key] = mtime
                    changed.append(key)
        return changed
