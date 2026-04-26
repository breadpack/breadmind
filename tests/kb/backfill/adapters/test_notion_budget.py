"""Tests for HourlyPageBudget instance-keyed integration (Task 14).

- test_hourly_budget_keyed_by_workspace_id
- test_hourly_budget_pause_preserves_cursor
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.kb.connectors.rate_limit import BudgetExceeded, HourlyPageBudget


_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000014")


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


# ---------------------------------------------------------------------------
# Task 14.1: Two workspaces under one org get separate budget dimensions
# ---------------------------------------------------------------------------


async def test_hourly_budget_keyed_by_workspace_id():
    """Same org, two different workspace IDs → separate HourlyPageBudget counters."""
    b = HourlyPageBudget(limit=2)
    org = uuid.uuid4()

    # workspace A: consume 2 → full
    await b.consume(org, count=2, instance_id="ws-alpha")
    with pytest.raises(BudgetExceeded):
        await b.consume(org, count=1, instance_id="ws-alpha")

    # workspace B: still has full budget
    await b.consume(org, count=2, instance_id="ws-beta")


# ---------------------------------------------------------------------------
# Task 14.2: Budget exceeded mid-run → BudgetExceeded propagates + cursor safe
# ---------------------------------------------------------------------------


async def test_hourly_budget_pause_preserves_cursor():
    """When HourlyPageBudget raises BudgetExceeded during discover(), the
    adapter should let the exception propagate so the BackfillRunner can
    capture the last cursor and mark the job as 'paused'."""
    from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter

    pages = [_make_page(f"page-{i}") for i in range(3)]
    client = MagicMock()
    client.request = AsyncMock(
        return_value={"object": "user", "id": "u1", "bot": {"workspace_id": "ws-1"}}
    )
    client.close = AsyncMock()
    client.list_block_children = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )
    client.query_database = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )

    async def fake_search(**_kw):
        return {"results": pages, "has_more": False, "next_cursor": None}

    client.search = AsyncMock(side_effect=fake_search)

    # Budget allows only 1 page then raises
    b = HourlyPageBudget(limit=1)

    adapter = NotionBackfillAdapter(
        org_id=_ORG_ID,
        source_filter={"workspace": "test"},
        since=_dt("2026-01-01T00:00:00Z"),
        until=_dt("2026-05-01T00:00:00Z"),
        dry_run=False,
        token_budget=1_000_000,
        client=client,
    )
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset(p["id"] for p in pages)
    adapter._budget = b

    collected = []
    with pytest.raises(BudgetExceeded):
        async for item in adapter.discover():
            collected.append(item)

    # At least one page was yielded before budget was exceeded
    assert len(collected) >= 1
    # Verify cursor can be computed from the last yielded item
    last = collected[-1]
    cursor = adapter.cursor_of(last)
    assert ":" in cursor
