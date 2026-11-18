"""64-bit SimHash computation and near-duplicate LSH clustering (Hamming <= 3)."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Sequence

from .. import SIMHASH_HAMMING_THRESHOLD
from ..models import FileRecord

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def _token_hash64(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def tokenize_for_simhash(text: str) -> list[str]:
    """Normalize text into lowercase alphanumeric tokens."""
    return _TOKEN_RE.findall(text.lower())


def compute_simhash64(tokens_or_text: str | Iterable[str]) -> int:
    """Compute a deterministic unsigned 64-bit SimHash fingerprint."""
    if isinstance(tokens_or_text, str):
        tokens = tokenize_for_simhash(tokens_or_text)
    else:
        tokens = [str(t).lower() for t in tokens_or_text if str(t).strip()]

    if not tokens:
        return 0

    weights = [0] * 64
    for tok in tokens:
        h = _token_hash64(tok)
        for bit in range(64):
            if (h >> bit) & 1:
                weights[bit] += 1
            else:
                weights[bit] -= 1

    fingerprint = 0
    for bit, score in enumerate(weights):
        if score >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance64(a: int, b: int) -> int:
    """Return Hamming distance between two 64-bit SimHash values."""
    xor = (a ^ b) & ((1 << 64) - 1)
    return xor.bit_count()


def cluster_near_duplicates(
    records: Sequence[FileRecord],
    *,
    max_distance: int = SIMHASH_HAMMING_THRESHOLD,
) -> dict[str, str]:
    """Group near-duplicate FileRecords (Hamming <= max_distance).

    Returns a mapping `{abs_path -> canonical_abs_path}` where the canonical file
    in each cluster is the record with the newest `mtime_ns` (ties broken by path).
    """
    ordered = sorted(records, key=lambda r: (-r.mtime_ns, r.abs_path))
    canonicals: list[FileRecord] = []
    mapping: dict[str, str] = {}

    for rec in ordered:
        matched_canon: FileRecord | None = None
        for cand in canonicals:
            if hamming_distance64(rec.simhash64, cand.simhash64) <= max_distance:
                matched_canon = cand
                break
        if matched_canon is None:
            canonicals.append(rec)
            mapping[rec.abs_path] = rec.abs_path
        else:
            mapping[rec.abs_path] = matched_canon.abs_path
    return mapping
