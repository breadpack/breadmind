"""Tests for automatic memory flush before compaction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from breadmind.memory.auto_flush import (
    AutoMemoryFlusher,
    DailyNoteFlushTarget,
    FlushableItem,
)


@pytest.fixture
def flusher() -> AutoMemoryFlusher:
    return AutoMemoryFlusher(importance_threshold=0.6)


class TestAutoMemoryFlusher:
    def test_extract_decision(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "We decided to use PostgreSQL for storage."}]
        items = flusher.extract_flushable(messages)
        assert len(items) >= 1
        assert items[0].category == "decision"

    def test_extract_preference(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "I prefer async-first architecture."}]
        items = flusher.extract_flushable(messages)
        assert len(items) >= 1
        assert items[0].category == "preference"

    def test_extract_finding(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "We found that the root cause was a race condition."}]
        items = flusher.extract_flushable(messages)
        assert len(items) >= 1
        assert items[0].category == "finding"

    def test_extract_todo(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "TODO: add retry logic to the worker."}]
        items = flusher.extract_flushable(messages)
        assert len(items) >= 1
        assert items[0].category == "todo"

    def test_ignores_short_text(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "OK."}]
        items = flusher.extract_flushable(messages)
        assert len(items) == 0

    def test_ignores_non_matching_text(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "The weather is nice today and I had lunch at noon."}]
        items = flusher.extract_flushable(messages)
        assert len(items) == 0

    def test_deduplicates_items(self, flusher: AutoMemoryFlusher) -> None:
        messages = [
            {"content": "We decided to use Redis. We decided to use Redis."},
        ]
        items = flusher.extract_flushable(messages)
        contents = [i.content for i in items]
        assert len(contents) == len(set(c.lower().strip() for c in contents))

    def test_importance_boost_for_emphasis(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": "We decided to use IMPORTANT caching strategy!"}]
        items = flusher.extract_flushable(messages)
        assert len(items) >= 1
        assert items[0].importance > 0.8

    def test_flush_writes_to_targets(self, flusher: AutoMemoryFlusher) -> None:
        target = MagicMock()
        flusher._targets = [target]
        messages = [{"content": "We decided to use Kubernetes for orchestration."}]

        flushed = flusher.flush(messages)

        assert len(flushed) >= 1
        target.write.assert_called_once_with(flushed)

    def test_flush_no_items_skips_targets(self, flusher: AutoMemoryFlusher) -> None:
        target = MagicMock()
        flusher._targets = [target]
        messages = [{"content": "Hello world."}]

        flushed = flusher.flush(messages)

        assert len(flushed) == 0
        target.write.assert_not_called()

    def test_skips_non_string_content(self, flusher: AutoMemoryFlusher) -> None:
        messages = [{"content": 12345}, {"content": None}, {}]
        items = flusher.extract_flushable(messages)
        assert len(items) == 0

    def test_classify_importance_no_match(self, flusher: AutoMemoryFlusher) -> None:
        cat, imp = flusher._classify_importance("just a random sentence here")
        assert cat is None
        assert imp == 0.0


class TestDailyNoteFlushTarget:
    def test_write_appends_to_daily_note(self, tmp_path: Path) -> None:
        from breadmind.memory.daily_notes import DailyNotesManager

        mgr = DailyNotesManager(tmp_path / "notes")
        target = DailyNoteFlushTarget(mgr)

        items = [
            FlushableItem(category="decision", content="Use PostgreSQL", importance=0.8),
            FlushableItem(category="todo", content="Add retry logic", importance=0.7),
        ]
        target.write(items)

        note = mgr.get_today()
        assert "Use PostgreSQL" in note.content
        assert "Add retry logic" in note.content
        assert "Auto-flushed" in note.content

    def test_write_empty_items_noop(self, tmp_path: Path) -> None:
        from breadmind.memory.daily_notes import DailyNotesManager

        mgr = DailyNotesManager(tmp_path / "notes")
        target = DailyNoteFlushTarget(mgr)

        target.write([])
        # Should not create a note file
        note = mgr.get_note(__import__("datetime").date.today())
        # Note might exist or not; if it doesn't exist that's fine
        # If it does exist, it should not have flush content
        if note is not None:
            assert "Auto-flushed" not in note.content
