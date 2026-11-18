"""Local TF-IDF / TextRank 25-word dense keyword fingerprint generator."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from .. import FINGERPRINT_MAX_WORDS

_WORD_RE = re.compile(r"[a-z][a-z0-9_]{1,30}")

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "will", "have", "has", "had", "not", "but", "you", "your", "our", "all",
    "can", "use", "used", "using", "into", "out", "new", "more", "than", "then",
    "when", "where", "which", "what", "who", "how", "why", "its", "it", "is",
    "in", "on", "at", "to", "of", "by", "as", "or", "an", "be", "if", "def",
    "return", "import", "from", "none", "true", "false", "self", "cls", "var",
    "let", "const", "function", "class",
})


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]


def extract_fingerprint_25w(
    text: str,
    *,
    headings: Sequence[str] = (),
    symbols: Sequence[str] = (),
    file_name: str = "",
    idf_map: Mapping[str, float] | None = None,
    max_words: int = FINGERPRINT_MAX_WORDS,
) -> str:
    """Generate a compact <= 25-word comma-separated keyword fingerprint."""
    body_tokens = _tokenize(text)
    heading_tokens = _tokenize(" ".join(headings))
    symbol_tokens = _tokenize(" ".join(symbols))
    name_tokens = _tokenize(file_name.replace("_", " ").replace("-", " ").replace(".", " "))

    all_tokens = name_tokens * 2 + heading_tokens * 2 + symbol_tokens + body_tokens
    if not all_tokens:
        return ""

    tf = Counter(all_tokens)
    vocab = list(tf.keys())

    # Co-occurrence window (size 4) for lightweight TextRank centrality
    neighbors: dict[str, set[str]] = defaultdict(set)
    window = 4
    for idx, tok in enumerate(all_tokens):
        end = min(len(all_tokens), idx + window)
        for j in range(idx + 1, end):
            other = all_tokens[j]
            if other != tok:
                neighbors[tok].add(other)
                neighbors[other].add(tok)

    scores: dict[str, float] = {w: 1.0 for w in vocab}
    damping = 0.85
    for _ in range(8):
        next_scores: dict[str, float] = {}
        for w in vocab:
            nbrs = neighbors.get(w)
            if not nbrs:
                next_scores[w] = 1.0 - damping
                continue
            rank_sum = sum(scores[n] / max(1, len(neighbors[n])) for n in nbrs)
            next_scores[w] = (1.0 - damping) + damping * rank_sum
        scores = next_scores

    # Combine TextRank + sub-linear TF-IDF + structural boost
    boosted: dict[str, float] = {}
    heading_set = set(heading_tokens) | set(name_tokens)
    symbol_set = set(symbol_tokens)
    for w, count in tf.items():
        idf = idf_map.get(w, 1.4) if idf_map is not None else 1.4
        tf_weight = 1.0 + math.log1p(count)
        struct_boost = 1.5 if w in heading_set else (1.25 if w in symbol_set else 1.0)
        boosted[w] = (tf_weight * idf * struct_boost) + (0.35 * scores.get(w, 0.0))

    ranked = sorted(boosted.items(), key=lambda item: (-item[1], item[0]))
    top_words = [w for w, _ in ranked[:max_words]]
    return ",".join(top_words)


def build_idf_map(documents: Iterable[str]) -> dict[str, float]:
    """Compute smoothed IDF weights across a corpus of documents."""
    docs = list(documents)
    n_docs = max(1, len(docs))
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(_tokenize(doc)))
    return {w: math.log((n_docs + 1.0) / (freq + 1.0)) + 1.0 for w, freq in df.items()}
