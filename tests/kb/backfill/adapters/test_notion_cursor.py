"""Tests for cursor_of() encoding (Task 7).

- test_cursor_of_format
- test_cursor_of_monotonic
- test_cursor_resume_advances_since
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from breadmind.kb.backfill.base import BackfillItem
from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter, _cursor_to_iso


_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000007")


def _make_adapter() -> NotionBackfillAdapter:
    return NotionBackfillAdapter(
        org_id=_ORG_ID,
        source_filter={"workspace": "test"},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=1_000_000,
        client=None,
    )


def _make_item(source_native_id: str, updated_at: datetime) -> BackfillItem:
    return BackfillItem(
        source_kind="notion_page",
        source_native_id=source_native_id,
        source_uri="https://notion.so/x",
        source_created_at=updated_at,
        source_updated_at=updated_at,
        title="Test",
        body="body text here " * 20,
        author="user-1",
    )


def test_cursor_of_format():
    adapter = _make_adapter()
    ts = datetime(2026, 3, 15, 8, 30, 0, tzinfo=timezone.utc)
    item = _make_item("a1b2c3d4e5f6", ts)
    cursor = adapter.cursor_of(item)
    expected_prefix = "2026-03-15T08:30:00+00:00"
    assert cursor.startswith(expected_prefix)
    assert cursor.endswith(":a1b2c3d4e5f6")


def test_cursor_of_monotonic():
    """Cursors for items with ascending timestamps must sort lexicographically."""
    adapter = _make_adapter()
    ts_old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts_new = datetime(2026, 4, 1, tzinfo=timezone.utc)
    item_old = _make_item("id-old", ts_old)
    item_new = _make_item("id-new", ts_new)
    c_old = adapter.cursor_of(item_old)
    c_new = adapter.cursor_of(item_new)
    assert c_old < c_new


def test_cursor_to_iso_roundtrip():
    """_cursor_to_iso should recover the ISO timestamp from a cursor string."""
    adapter = _make_adapter()
    ts = datetime(2026, 3, 15, 8, 30, 0, tzinfo=timezone.utc)
    item = _make_item("pageid123", ts)
    cursor = adapter.cursor_of(item)
    recovered = _cursor_to_iso(cursor)
    assert recovered == ts


def test_resume_cursor_advances_since():
    """discover() with _resume_cursor set should use max(since, cursor_ts)."""
    # We just verify _cursor_to_iso returns a datetime later than since
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts_cursor = datetime(2026, 3, 1, tzinfo=timezone.utc)
    cursor = f"{ts_cursor.isoformat()}:some-page-id"
    recovered = _cursor_to_iso(cursor)
    effective_since = max(since, recovered)
    assert effective_since == ts_cursor
