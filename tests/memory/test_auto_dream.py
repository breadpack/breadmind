"""Tests for AutoDream memory consolidation."""
from __future__ import annotations

import time

from breadmind.memory.auto_dream import (
    AutoDreamer,
    ConsolidationReport,
    DreamAction,
    MemoryEntry,
)


def _make_entry(
    id: str,
    content: str,
    category: str = "finding",
    days_ago: float = 0,
    access_count: int = 1,
) -> MemoryEntry:
    now = time.time()
    created = now - (days_ago * 86400)
    return MemoryEntry(
        id=id,
        content=content,
        category=category,
        created_at=created,
        last_accessed=created,
        access_count=access_count,
    )


def test_identify_stale_entries():
    dreamer = AutoDreamer(stale_days=30)
    entries = [
        _make_entry("old1", "some old finding", days_ago=60, access_count=1),
        _make_entry("recent1", "recent finding", days_ago=5, access_count=1),
    ]
    results = dreamer.identify_stale(entries)
    assert len(results) == 1
    assert results[0].action == DreamAction.PRUNE
    assert "old1" in results[0].source_entries


def test_stale_spares_frequently_accessed():
    """Entries accessed 3+ times should not be pruned even if old."""
    dreamer = AutoDreamer(stale_days=30)
    entries = [
        _make_entry("old_popular", "important info", days_ago=60, access_count=5),
    ]
    results = dreamer.identify_stale(entries)
    assert len(results) == 0


def test_identify_duplicates():
    dreamer = AutoDreamer(similarity_threshold=0.6)
    entries = [
        _make_entry("a", "the kubernetes deployment failed with timeout error"),
        _make_entry("b", "kubernetes deployment failed due to timeout error"),
        _make_entry("c", "completely different topic about python testing"),
    ]
    results = dreamer.identify_duplicates(entries)
    assert len(results) == 1
    assert results[0].action == DreamAction.MERGE
    assert set(results[0].source_entries) == {"a", "b"}


def test_no_duplicates_when_dissimilar():
    dreamer = AutoDreamer(similarity_threshold=0.7)
    entries = [
        _make_entry("x", "kubernetes pod scheduling algorithms"),
        _make_entry("y", "python asyncio event loop internals"),
    ]
    results = dreamer.identify_duplicates(entries)
    assert len(results) == 0


def test_jaccard_similarity():
    dreamer = AutoDreamer()
    assert dreamer._jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0
    assert dreamer._jaccard_similarity(set(), set()) == 1.0
    assert dreamer._jaccard_similarity({"a"}, set()) == 0.0
    sim = dreamer._jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
    assert abs(sim - 0.5) < 0.01


def test_consolidate_full_cycle():
    dreamer = AutoDreamer(stale_days=30, similarity_threshold=0.6)
    entries = [
        _make_entry("stale1", "old stale info", days_ago=60, access_count=0),
        _make_entry("dup1", "deploy kubernetes cluster with helm chart"),
        _make_entry("dup2", "deploy kubernetes cluster using helm chart"),
        _make_entry("fresh", "brand new unique finding", days_ago=1),
    ]
    report = dreamer.consolidate(entries)
    assert isinstance(report, ConsolidationReport)
    assert report.pruned == 1
    assert report.merged == 1
    assert report.kept >= 1
    assert report.duration_ms >= 0


def test_apply_results_prune_and_merge():
    dreamer = AutoDreamer(stale_days=30, similarity_threshold=0.6)
    entries = [
        _make_entry("stale1", "old info", days_ago=60, access_count=0),
        _make_entry("dup1", "deploy kubernetes cluster with helm chart", access_count=3),
        _make_entry("dup2", "deploy kubernetes cluster using helm chart", access_count=1),
        _make_entry("keep1", "unique recent finding", days_ago=1),
    ]
    report = dreamer.consolidate(entries)
    result = dreamer.apply_results(entries, report.details)

    result_ids = {e.id for e in result}
    assert "stale1" not in result_ids  # pruned
    assert "keep1" in result_ids  # kept
    # One of the duplicates should remain as merged
    assert len(result) < len(entries)


def test_should_run():
    dreamer = AutoDreamer()
    assert dreamer.should_run(None) is True
    assert dreamer.should_run(time.time(), min_interval_hours=24) is False
    old_time = time.time() - (25 * 3600)
    assert dreamer.should_run(old_time, min_interval_hours=24) is True


def test_word_set_normalization():
    dreamer = AutoDreamer()
    words = dreamer._word_set("Hello World! This is a TEST_123.")
    assert "hello" in words
    assert "world" in words
    assert "test_123" in words
    # Short words (<=2 chars) filtered out
    assert "is" not in words
    assert "a" not in words


def test_empty_entries():
    dreamer = AutoDreamer()
    report = dreamer.consolidate([])
    assert report.pruned == 0
    assert report.merged == 0
    assert report.kept == 0


def test_merge_preserves_higher_access_count():
    """When merging, the entry with higher access count should be primary."""
    dreamer = AutoDreamer(similarity_threshold=0.5)
    entries = [
        _make_entry("low", "kubernetes deployment timeout error", access_count=1),
        _make_entry("high", "kubernetes deployment timeout error fixed", access_count=10),
    ]
    results = dreamer.identify_duplicates(entries)
    assert len(results) == 1
    # Apply and check the merged entry retains combined access count
    applied = dreamer.apply_results(entries, results)
    assert len(applied) == 1
    merged = applied[0]
    assert merged.access_count == 11
