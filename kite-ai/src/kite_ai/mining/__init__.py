"""Local CPU content extraction, 64-bit SimHash deduplication, and TextRank fingerprinting."""

from __future__ import annotations

from .extractor import ExtractedContent, extract_content, infer_platform_badge
from .simhash import cluster_near_duplicates, compute_simhash64, hamming_distance64
from .textrank import extract_fingerprint_25w

__all__ = [
    "ExtractedContent",
    "cluster_near_duplicates",
    "compute_simhash64",
    "extract_content",
    "extract_fingerprint_25w",
    "hamming_distance64",
    "infer_platform_badge",
]
