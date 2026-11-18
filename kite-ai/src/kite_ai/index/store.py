"""SQLite FTS5 (bm25 + trigram) local retrieval store with SimHash deduplication."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

from .. import SIMHASH_HAMMING_THRESHOLD
from ..mining.extractor import extract_content
from ..mining.simhash import compute_simhash64, hamming_distance64
from ..mining.textrank import extract_fingerprint_25w
from ..models import FileRecord, IndexTelemetry, SearchHit
from ..privacy import PrivacyFilter

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_WORD_RE = re.compile(r"[a-z0-9_]{2,}")


def _to_signed64(val: int) -> int:
    u = val & ((1 << 64) - 1)
    return u - (1 << 64) if u >= (1 << 63) else u


def _to_unsigned64(val: int) -> int:
    return val & ((1 << 64) - 1)


def compute_query_hash(query: str, provider: str = "offline", max_tokens: int = 400) -> str:
    norm = f"{provider.lower()}|{max_tokens}|{' '.join(query.lower().split())}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


class IndexStore:
    """Zero-idle-RAM embedded SQLite FTS5 index & semantic query cache."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        privacy: PrivacyFilter | None = None,
    ) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.privacy = privacy or PrivacyFilter()
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> IndexStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def upsert_record(self, record: FileRecord) -> int:
        """Insert or update a FileRecord and return its file_id."""
        file_name = record.file_name or Path(record.abs_path).name
        simhash_signed = _to_signed64(record.simhash64)
        cur = self._conn.execute(
            """
            INSERT INTO files_meta (
                abs_path, file_name, headings, inode, mtime_ns, size_bytes,
                platform_badge, simhash64, canonical_file_id, fingerprint_25w
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(abs_path) DO UPDATE SET
                file_name=excluded.file_name,
                headings=excluded.headings,
                inode=excluded.inode,
                mtime_ns=excluded.mtime_ns,
                size_bytes=excluded.size_bytes,
                platform_badge=excluded.platform_badge,
                simhash64=excluded.simhash64,
                canonical_file_id=excluded.canonical_file_id,
                fingerprint_25w=excluded.fingerprint_25w
            """,
            (
                record.abs_path,
                file_name,
                record.headings,
                int(record.inode),
                int(record.mtime_ns),
                int(record.size_bytes),
                record.platform_badge,
                simhash_signed,
                record.canonical_file_id,
                record.fingerprint_25w,
            ),
        )
        row = self._conn.execute(
            "SELECT file_id FROM files_meta WHERE abs_path = ?",
            (record.abs_path,),
        ).fetchone()
        self._conn.commit()
        return int(row["file_id"]) if row is not None else int(cur.lastrowid or 0)

    def refresh_duplicate_clusters(self, *, max_distance: int = SIMHASH_HAMMING_THRESHOLD) -> None:
        """Assign canonical_file_id across near-duplicate clusters (Hamming <= max_distance)."""
        rows = self._conn.execute(
            "SELECT file_id, abs_path, mtime_ns, simhash64 FROM files_meta ORDER BY mtime_ns DESC, abs_path ASC"
        ).fetchall()
        canonicals: list[tuple[int, int]] = []
        updates: list[tuple[int, int]] = []

        for row in rows:
            fid = int(row["file_id"])
            sh = _to_unsigned64(int(row["simhash64"]))
            canon_id: int | None = None
            for c_id, c_sh in canonicals:
                if hamming_distance64(sh, c_sh) <= max_distance:
                    canon_id = c_id
                    break
            if canon_id is None:
                canonicals.append((fid, sh))
                updates.append((fid, fid))
            else:
                updates.append((canon_id, fid))

        self._conn.executemany(
            "UPDATE files_meta SET canonical_file_id = ? WHERE file_id = ?",
            updates,
        )
        self._conn.commit()

    def index_directory(self, root: str | Path, *, force: bool = False) -> dict[str, int]:
        """Incrementally index safe files under `root`, skipping unchanged (inode, mtime_ns)."""
        root_path = Path(root)
        stats = {"indexed": 0, "skipped_unchanged": 0, "blocked_privacy": 0}
        if not root_path.exists():
            return stats

        existing_rows = {
            row["abs_path"]: (int(row["inode"]), int(row["mtime_ns"]))
            for row in self._conn.execute("SELECT abs_path, inode, mtime_ns FROM files_meta").fetchall()
        }

        db_resolved = Path(self.db_path).resolve() if self.db_path != ":memory:" else None
        for item in sorted(root_path.rglob("*")):
            if not item.is_file():
                continue
            if db_resolved is not None and item.resolve().name.startswith(db_resolved.name) and item.resolve().parent == db_resolved.parent:
                continue
            if self.privacy.is_blocked(item, root=root_path):
                stats["blocked_privacy"] += 1
                continue

            st = item.stat()
            abs_str = item.resolve().as_posix()
            inode = int(getattr(st, "st_ino", 0))
            mtime_ns = int(st.st_mtime_ns)
            if not force and existing_rows.get(abs_str) == (inode, mtime_ns):
                stats["skipped_unchanged"] += 1
                continue

            extracted = extract_content(item)
            headings_str = " | ".join(extracted.headings)
            fp_25w = extract_fingerprint_25w(
                extracted.text_sample,
                headings=extracted.headings,
                symbols=extracted.symbols,
                file_name=extracted.file_name,
            )
            simhash = compute_simhash64(
                f"{headings_str} {' '.join(extracted.symbols)} {extracted.text_sample[:4000]}"
            )
            self.upsert_record(
                FileRecord(
                    abs_path=abs_str,
                    file_name=extracted.file_name,
                    headings=headings_str,
                    inode=inode,
                    mtime_ns=mtime_ns,
                    size_bytes=int(st.st_size),
                    platform_badge=extracted.platform_badge,
                    simhash64=simhash,
                    fingerprint_25w=fp_25w,
                )
            )
            stats["indexed"] += 1

        if stats["indexed"] > 0:
            self.refresh_duplicate_clusters()
        return stats

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        collapse_duplicates: bool = True,
    ) -> list[SearchHit]:
        """Hybrid SQLite FTS5 (bm25 + trigram) search with duplicate collapsing."""
        q_clean = query.strip()
        if not q_clean:
            return []

        tokens = _WORD_RE.findall(q_clean.lower())
        trigram_terms = [t for t in tokens if len(t) >= 3]
        raw_hits: list[tuple[sqlite3.Row, float]] = []

        if trigram_terms:
            fts_expr = " OR ".join(f'"{t}"' for t in trigram_terms[:8])
            try:
                rows = self._conn.execute(
                    """
                    SELECT m.*, bm25(files_fts, 4.0, 2.5, 1.5) AS rank_score
                    FROM files_fts
                    JOIN files_meta m ON m.file_id = files_fts.rowid
                    WHERE files_fts MATCH ?
                      AND (? = 0 OR m.file_id = COALESCE(m.canonical_file_id, m.file_id))
                    ORDER BY rank_score ASC, m.mtime_ns DESC
                    LIMIT ?
                    """,
                    (fts_expr, 1 if collapse_duplicates else 0, max(limit * 4, 25)),
                ).fetchall()
                raw_hits = [(r, float(r["rank_score"])) for r in rows]
            except sqlite3.OperationalError:
                raw_hits = []

        # Fallback lexical match for short (<3 char) or multi-keyword partial queries
        if not raw_hits and tokens:
            all_rows = self._conn.execute("SELECT * FROM files_meta ORDER BY mtime_ns DESC").fetchall()
            scored_fallback: list[tuple[sqlite3.Row, float]] = []
            for r in all_rows:
                if collapse_duplicates and int(r["file_id"]) != int(r["canonical_file_id"] or r["file_id"]):
                    continue
                hay = f"{r['file_name']} {r['headings']} {r['fingerprint_25w']}".lower()
                matched = sum(1 for tok in tokens if tok in hay)
                if matched > 0:
                    scored_fallback.append((r, -float(matched)))
            scored_fallback.sort(key=lambda item: (item[1], -int(item[0]["mtime_ns"])))
            raw_hits = scored_fallback[: max(limit * 4, 25)]

        # Count cluster sizes for badge display
        cluster_counts: dict[int, int] = {}
        for row in self._conn.execute("SELECT file_id, canonical_file_id FROM files_meta").fetchall():
            cid = int(row["canonical_file_id"] or row["file_id"])
            cluster_counts[cid] = cluster_counts.get(cid, 0) + 1

        seen_canonicals: set[int] = set()
        results: list[SearchHit] = []
        for r, rank_score in raw_hits:
            fid = int(r["file_id"])
            cid = int(r["canonical_file_id"] or fid)
            if collapse_duplicates and cid in seen_canonicals:
                continue
            seen_canonicals.add(cid)

            hay = f"{r['file_name']} {r['headings']} {r['fingerprint_25w']}".lower()
            token_cov = sum(1 for t in tokens if t in hay) / max(1, len(tokens))
            bm25_mag = min(1.0, abs(rank_score) / 10.0)
            confidence = round(min(0.99, max(0.15, 0.65 * token_cov + 0.35 * bm25_mag)), 3)

            results.append(
                SearchHit(
                    file_id=fid,
                    abs_path=str(r["abs_path"]),
                    file_name=str(r["file_name"]),
                    mtime_ns=int(r["mtime_ns"]),
                    size_bytes=int(r["size_bytes"]),
                    platform_badge=str(r["platform_badge"]),
                    simhash64=_to_unsigned64(int(r["simhash64"])),
                    canonical_file_id=cid,
                    fingerprint_25w=str(r["fingerprint_25w"]),
                    headings=str(r["headings"]),
                    bm25_score=rank_score,
                    confidence=confidence,
                    duplicate_count=cluster_counts.get(cid, 1),
                )
            )
            if len(results) >= limit:
                break

        return results

    def max_mtime_ns(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(mtime_ns), 0) AS mx FROM files_meta").fetchone()
        return int(row["mx"]) if row is not None else 0

    def get_cached_query(self, query_hash: str) -> str | None:
        current_max = self.max_mtime_ns()
        row = self._conn.execute(
            "SELECT max_mtime_ns, response_json FROM query_cache WHERE query_hash = ?",
            (query_hash,),
        ).fetchone()
        if row is None or int(row["max_mtime_ns"]) < current_max:
            return None
        return str(row["response_json"])

    def put_cached_query(self, query_hash: str, response_json: str, created_at: int) -> None:
        current_max = self.max_mtime_ns()
        self._conn.execute(
            """
            INSERT INTO query_cache (query_hash, max_mtime_ns, response_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                max_mtime_ns=excluded.max_mtime_ns,
                response_json=excluded.response_json,
                created_at=excluded.created_at
            """,
            (query_hash, current_max, response_json, int(created_at)),
        )
        self._conn.commit()

    def telemetry(self) -> IndexTelemetry:
        total = int(self._conn.execute("SELECT COUNT(*) FROM files_meta").fetchone()[0])
        canon = int(
            self._conn.execute(
                "SELECT COUNT(DISTINCT COALESCE(canonical_file_id, file_id)) FROM files_meta"
            ).fetchone()[0]
        )
        cache_entries = int(self._conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0])
        db_bytes = os.path.getsize(self.db_path) if self.db_path != ":memory:" and Path(self.db_path).exists() else 0
        return IndexTelemetry(
            total_files=total,
            canonical_files=canon,
            duplicate_collapsed=max(0, total - canon),
            max_mtime_ns=self.max_mtime_ns(),
            cache_entries=cache_entries,
            db_size_bytes=db_bytes,
        )
