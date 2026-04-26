"""Tests for per-page failure isolation (Task 10).

Verifies that a RuntimeError on one page does not abort the entire run
and that subsequent pages are still processed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter


_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _make_page(page_id: str, *, last_edited: str = "2026-03-01T00:00:00Z") -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": last_edited,
        "archived": False,
        "in_trash": False,
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "title": {"id": "title", "type": "title", "title": [{"plain_text": f"Page {page_id}"}]}
        },
        "created_by": {"id": "user-1"},
    }


async def test_per_page_error_does_not_abort_run():
    """5 pages, 3rd raises RuntimeError → 4th and 5th still processed."""
    pages = [_make_page(f"page-{i}") for i in range(1, 6)]
    error_page_id = "page-3"

    client = MagicMock()
    client.request = AsyncMock(
        return_value={"object": "user", "id": "u1", "bot": {"workspace_id": "ws-1"}}
    )
    client.close = AsyncMock()

    async def fake_search(**_kw):
        return {"results": pages, "has_more": False, "next_cursor": None}

    client.search = AsyncMock(side_effect=fake_search)

    async def fake_list_blocks(block_id, **_kw):
        if block_id == error_page_id:
            raise RuntimeError("simulated block fetch failure")
        return {"results": [], "has_more": False, "next_cursor": None}

    client.list_block_children = AsyncMock(side_effect=fake_list_blocks)
    client.query_database = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )

    adapter = NotionBackfillAdapter(
        org_id=_ORG_ID,
        source_filter={"workspace": "test"},
        since=_dt("2026-01-01T00:00:00Z"),
        until=_dt("2026-05-01T00:00:00Z"),
        dry_run=True,
        token_budget=1_000_000,
        client=client,
    )
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset(p["id"] for p in pages)

    items = [item async for item in adapter.discover()]
    item_ids = [i.source_native_id for i in items]

    # All 5 pages should appear (either as real items or error-marked items)
    for i in range(1, 6):
        assert f"page-{i}" in item_ids, f"page-{i} missing from discover output"

    # The failing page should have _fetch_error set
    error_item = next(i for i in items if i.source_native_id == error_page_id)
    assert "_fetch_error" in error_item.extra

    # Pages 4 and 5 should be normal (no error)
    normal_after = [i for i in items if i.source_native_id in ("page-4", "page-5")]
    assert len(normal_after) == 2
    for item in normal_after:
        assert "_fetch_error" not in item.extra
