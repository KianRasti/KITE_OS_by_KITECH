"""Privacy guardrail (.kiteignore matcher & built-in sensitive path blocker).

Evaluated strictly BEFORE opening or reading any file contents from disk.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

BUILTIN_BLOCKED_SEGMENTS = (
    ".ssh",
    ".gnupg",
    ".git",
    "__pycache__",
    "node_modules",
)

BUILTIN_BLOCKED_PREFIXES = (
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/sudoers",
)

BUILTIN_BLOCKED_SUBPATHS = (
    ".mozilla/firefox",
    ".config/chromium",
    ".config/google-chrome",
    ".config/bravesoftware",
    ".local/share/keyrings",
)

BUILTIN_BLOCKED_FILENAME_PATTERNS = (
    ".env",
    ".env.*",
    "*.env",
    "*id_rsa*",
    "*id_ed25519*",
    "*id_ecdsa*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "shadow",
    "gshadow",
)


def parse_kiteignore(text: str) -> list[str]:
    """Parse .kiteignore lines into clean pattern strings."""
    patterns: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


class PrivacyFilter:
    """Blocks sensitive credentials, keys, browser profiles, and .kiteignore paths."""

    def __init__(
        self,
        patterns: Sequence[str] = (),
        *,
        kiteignore_path: Path | None = None,
    ) -> None:
        loaded: list[str] = list(patterns)
        if kiteignore_path is not None and kiteignore_path.is_file():
            loaded.extend(parse_kiteignore(kiteignore_path.read_text(encoding="utf-8", errors="replace")))
        self.patterns: tuple[str, ...] = tuple(dict.fromkeys(loaded))

    def is_blocked(self, path: str | Path, *, root: str | Path | None = None) -> bool:
        """Return True when `path` must NEVER be opened or indexed."""
        raw = str(path).replace("\\", "/")
        lower = raw.lower()
        posix = PurePosixPath(lower)
        parts = posix.parts
        name = posix.name

        for prefix in BUILTIN_BLOCKED_PREFIXES:
            if lower == prefix or lower.startswith(prefix + "/"):
                return True

        for seg in BUILTIN_BLOCKED_SEGMENTS:
            if seg in parts:
                return True

        for sub in BUILTIN_BLOCKED_SUBPATHS:
            if f"/{sub}" in lower or lower.startswith(sub):
                return True

        for pat in BUILTIN_BLOCKED_FILENAME_PATTERNS:
            if fnmatch.fnmatch(name, pat):
                return True

        rel = lower
        if root is not None:
            root_norm = str(root).replace("\\", "/").rstrip("/").lower()
            if root_norm and lower.startswith(root_norm + "/"):
                rel = lower[len(root_norm) + 1 :]

        for raw_pat in self.patterns:
            pat = raw_pat.replace("\\", "/").lower()
            clean = pat.rstrip("/")
            if pat.endswith("/"):
                if clean in parts or rel.startswith(clean + "/") or f"/{clean}/" in lower:
                    return True
            if fnmatch.fnmatch(name, clean) or fnmatch.fnmatch(rel, clean) or fnmatch.fnmatch(lower, f"*{clean}*"):
                return True
        return False

    def filter_paths(self, paths: Iterable[str | Path], *, root: str | Path | None = None) -> list[str]:
        """Return only safe, non-blocked paths."""
        return [str(p) for p in paths if not self.is_blocked(p, root=root)]
