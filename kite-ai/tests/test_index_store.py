"""Unit tests for SQLite FTS5 IndexStore, incremental mtime skip, and query_cache."""

from __future__ import annotations

import time
from pathlib import Path

from kite_ai.index.store import IndexStore, compute_query_hash
from kite_ai.privacy import PrivacyFilter


def test_index_directory_respects_privacy_and_incremental_skip(tmp_path: Path) -> None:
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("PRIVATE KEY", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (tmp_path / "Greenhouse_Spec.md").write_text(
        "# University Capstone Greenhouse\nESP32 PID controller for fan and irrigation.\n",
        encoding="utf-8",
    )
    (tmp_path / "tent_monitor.ino").write_text(
        "void setupPwmFan() {} // esp32cam pwm led fan greenhouse\n",
        encoding="utf-8",
    )

    with IndexStore(tmp_path / "index.db", privacy=PrivacyFilter()) as store:
        s1 = store.index_directory(tmp_path)
        assert s1["indexed"] == 2
        assert s1["blocked_privacy"] >= 2

        s2 = store.index_directory(tmp_path)
        assert s2["indexed"] == 0
        assert s2["skipped_unchanged"] == 2

        hits = store.search("greenhouse esp32")
        assert len(hits) >= 2
        assert hits[0].confidence > 0.2


def test_index_store_simhash_duplicate_collapsing_picks_newest(tmp_path: Path) -> None:
    text = (
        "University capstone greenhouse automation report chapter two bill of materials and pid schedule "
        "esp32 sensor calibration relay irrigation firmware telemetry validation testing results "
    ) * 3
    old_f = tmp_path / "Report_v1.md"
    old_f.write_text(text, encoding="utf-8")
    new_f = tmp_path / "Report_v2.md"
    new_f.write_text(text + "final\n", encoding="utf-8")
    # Ensure distinct mtime_ns
    import os
    os.utime(old_f, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new_f, ns=(2_000_000_000, 2_000_000_000))

    with IndexStore(":memory:") as store:
        store.index_directory(tmp_path)
        collapsed = store.search("capstone greenhouse report", collapse_duplicates=True)
        uncollapsed = store.search("capstone greenhouse report", collapse_duplicates=False)
        assert len(uncollapsed) == 2
        assert len(collapsed) == 1
        assert collapsed[0].file_name == "Report_v2.md"
        assert collapsed[0].duplicate_count == 2


def test_index_store_trigram_substring_and_query_cache_invalidation(tmp_path: Path) -> None:
    doc = tmp_path / "Agile_Report_Ch2.md"
    doc.write_text("# Agile Methodology\nSprint backlog and greenhouse BOM.\n", encoding="utf-8")

    with IndexStore(tmp_path / "idx.db") as store:
        store.index_directory(tmp_path)
        t0 = time.perf_counter()
        hits = store.search("Agile_Report")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert hits and hits[0].file_name == "Agile_Report_Ch2.md"
        assert elapsed_ms < 250.0

        qh = compute_query_hash("agile methodology", provider="gemini", max_tokens=400)
        store.put_cached_query(qh, '{"groups":[],"action":null}', created_at=100)
        assert store.get_cached_query(qh) == '{"groups":[],"action":null}'

        # Adding newer file advances max_mtime_ns -> invalidates stale cache entry
        newer = tmp_path / "Agile_Report_Ch3.md"
        newer.write_text("# Agile Ch3\nUpdated release.\n", encoding="utf-8")
        import os
        os.utime(newer, ns=(store.max_mtime_ns() + 1_000_000, store.max_mtime_ns() + 1_000_000))
        store.index_directory(tmp_path)
        assert store.get_cached_query(qh) is None

        tel = store.telemetry()
        assert tel.total_files == 2
        assert tel.db_size_bytes > 0
