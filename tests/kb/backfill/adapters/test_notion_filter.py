"""Tests for NotionBackfillAdapter.filter() — Tasks 8 & 9.

Tests all 10 §4 signal filter keys and evaluation order.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from breadmind.kb.backfill.base import BackfillItem
from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter


_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000008")
_NOW = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _make_adapter(share_in: frozenset[str] | None = None) -> NotionBackfillAdapter:
    adapter = NotionBackfillAdapter(
        org_id=_ORG_ID,
        source_filter={"workspace": "test"},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=1_000_000,
        client=None,
    )
    adapter._share_in_snapshot = share_in if share_in is not None else frozenset()
    adapter._workspace_id = "ws-1"
    return adapter


def _item(
    *,
    page_id: str = "page-001",
    title: str = "Normal Page",
    body: str = "x" * 200,
    extra: dict | None = None,
    source_kind: str = "notion_page",
) -> BackfillItem:
    return BackfillItem(
        source_kind=source_kind,
        source_native_id=page_id,
        source_uri="https://notion.so/x",
        source_created_at=_NOW,
        source_updated_at=_NOW,
        title=title,
        body=body,
        author="user-1",
        extra=dict(extra or {}),
    )


# ---------------------------------------------------------------------------
# Rule 1: archived
# ---------------------------------------------------------------------------


def test_filter_drops_archived():
    adapter = _make_adapter()
    item = _item(extra={"archived": True})
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "archived"


# ---------------------------------------------------------------------------
# Rule 2: in_trash
# ---------------------------------------------------------------------------


def test_filter_drops_in_trash():
    adapter = _make_adapter()
    item = _item(extra={"in_trash": True})
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "in_trash"


# ---------------------------------------------------------------------------
# Rule 3: template
# ---------------------------------------------------------------------------


def test_filter_drops_template_flag():
    adapter = _make_adapter()
    item = _item(extra={"template": True})
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "template"


def test_filter_drops_template_title_prefix():
    adapter = _make_adapter()
    item = _item(title="Template: Onboarding")
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "template"


# ---------------------------------------------------------------------------
# Rule 4: acl_lock
# ---------------------------------------------------------------------------


def test_filter_drops_acl_lock_when_not_in_snapshot():
    """Page not in share-in snapshot → acl_lock."""
    adapter = _make_adapter(share_in=frozenset(["other-page"]))
    item = _item(page_id="page-not-shared")
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "acl_lock"


def test_filter_passes_when_in_snapshot():
    adapter = _make_adapter(share_in=frozenset(["page-001"]))
    item = _item(page_id="page-001", body="x" * 200)
    assert adapter.filter(item) is True


# ---------------------------------------------------------------------------
# Rule 5: share_revoked (pre-set by discover)
# ---------------------------------------------------------------------------


def test_filter_drops_share_revoked():
    adapter = _make_adapter()
    item = _item(extra={"_skip_reason": "share_revoked"})
    assert adapter.filter(item) is False


# ---------------------------------------------------------------------------
# Rule 6: title_only
# ---------------------------------------------------------------------------


def test_filter_drops_title_only():
    adapter = _make_adapter()
    item = _item(extra={"_block_count": 0})
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "title_only"


# ---------------------------------------------------------------------------
# Rule 7: empty_page
# ---------------------------------------------------------------------------


def test_filter_drops_empty_page():
    """Body shorter than 120 chars → empty_page."""
    adapter = _make_adapter()
    item = _item(body="short")
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "empty_page"


def test_filter_passes_sufficient_body():
    adapter = _make_adapter(share_in=frozenset(["page-001"]))
    item = _item(body="x" * 150)
    assert adapter.filter(item) is True


# ---------------------------------------------------------------------------
# Rule 8: oversized
# ---------------------------------------------------------------------------


def test_filter_drops_oversized():
    adapter = _make_adapter()
    item = _item(body="x" * 200_001)
    assert adapter.filter(item) is False
    assert item.extra["_skip_reason"] == "oversized"


# ---------------------------------------------------------------------------
# Rule 9: duplicate_body
# ---------------------------------------------------------------------------


def test_filter_drops_duplicate_body_same_run():
    adapter = _make_adapter()
    body = "y" * 200
    item1 = _item(page_id="page-a", body=body)
    item2 = _item(page_id="page-b", body=body)  # same body, same title
    assert adapter.filter(item1) is True
    assert adapter.filter(item2) is False
    assert item2.extra["_skip_reason"] == "duplicate_body"


def test_filter_different_bodies_not_duplicate():
    adapter = _make_adapter()
    item1 = _item(page_id="page-c", body="a" * 200)
    item2 = _item(page_id="page-d", body="b" * 200)
    assert adapter.filter(item1) is True
    assert adapter.filter(item2) is True


# ---------------------------------------------------------------------------
# Rule evaluation order: if a page matches 2 rules, first wins
# ---------------------------------------------------------------------------


def test_filter_archived_takes_precedence_over_empty_page():
    """archived > empty_page in evaluation order."""
    adapter = _make_adapter()
    item = _item(body="tiny", extra={"archived": True, "in_trash": True})
    adapter.filter(item)
    assert item.extra["_skip_reason"] == "archived"


def test_filter_in_trash_takes_precedence_over_template():
    """in_trash > template."""
    adapter = _make_adapter()
    item = _item(title="Template: Foo", extra={"in_trash": True})
    adapter.filter(item)
    assert item.extra["_skip_reason"] == "in_trash"
