"""Tests for NotionBackfillAdapter ACL / share-in snapshot (Tasks 3 & 9).

Task 3:
- prepare() snapshots visible pages into _share_in_snapshot
- prepare() propagates auth failure as PermissionError

Task 9:
- mid-run 404 during discover block fetch → share_revoked skip
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_WORKSPACE = "pilot-alpha"


def _make_page(page_id: str) -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": "2026-04-01T00:00:00Z",
        "archived": False,
        "in_trash": False,
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "title": {
                "id": "title",
                "type": "title",
                "title": [{"plain_text": f"Page {page_id}"}],
            }
        },
        "created_by": {"id": "user-1"},
    }


def _make_fake_client(search_results: list[dict], *, raise_auth: bool = False):
    """Build a fake NotionClient."""
    client = MagicMock()
    if raise_auth:
        from aiohttp import ClientResponseError
        client.request = AsyncMock(
            side_effect=ClientResponseError(
                request_info=MagicMock(), history=(), status=401
            )
        )
        client.search = AsyncMock(
            side_effect=ClientResponseError(
                request_info=MagicMock(), history=(), status=401
            )
        )
    else:
        me_resp = {
            "object": "user",
            "id": "user-1",
            "bot": {"workspace_id": "ws-abc123"},
        }
        client.request = AsyncMock(return_value=me_resp)
        # search called with paging; first call returns all, second empty
        search_resp_1 = {
            "results": search_results,
            "has_more": False,
            "next_cursor": None,
        }
        client.search = AsyncMock(return_value=search_resp_1)
    client.close = AsyncMock()
    return client


def _make_adapter(client=None, workspace: str = _WORKSPACE) -> NotionBackfillAdapter:
    from datetime import datetime, timezone
    return NotionBackfillAdapter(
        org_id=_ORG_ID,
        source_filter={"workspace": workspace},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 1, tzinfo=timezone.utc),
        dry_run=True,
        token_budget=1_000_000,
        client=client,
    )


# ---------------------------------------------------------------------------
# Task 3: prepare() snapshots visible pages
# ---------------------------------------------------------------------------


async def test_prepare_snapshots_visible_pages():
    pages = [_make_page(f"page-{i}") for i in range(5)]
    fake_client = _make_fake_client(pages)
    adapter = _make_adapter(client=fake_client)

    await adapter.prepare()

    assert hasattr(adapter, "_share_in_snapshot")
    assert isinstance(adapter._share_in_snapshot, frozenset)
    assert len(adapter._share_in_snapshot) == 5
    for i in range(5):
        assert f"page-{i}" in adapter._share_in_snapshot


async def test_prepare_stores_workspace_id():
    fake_client = _make_fake_client([])
    adapter = _make_adapter(client=fake_client)

    await adapter.prepare()

    assert adapter._workspace_id == "ws-abc123"


async def test_prepare_propagates_auth_failure():
    fake_client = _make_fake_client([], raise_auth=True)
    adapter = _make_adapter(client=fake_client)

    with pytest.raises(PermissionError):
        await adapter.prepare()


async def test_instance_id_of_returns_workspace_id():
    fake_client = _make_fake_client([])
    adapter = _make_adapter(client=fake_client)
    await adapter.prepare()

    iid = adapter.instance_id_of({"workspace": _WORKSPACE})
    assert iid == "ws-abc123"


# ---------------------------------------------------------------------------
# Task 9: mid-run 404 → share_revoked
# ---------------------------------------------------------------------------


async def test_mid_run_404_is_share_revoked():
    """discover() fetching blocks for a page that returns 404 should mark
    that page as share_revoked and not propagate the exception."""
    from aiohttp import ClientResponseError
    from datetime import datetime, timezone

    pages = [_make_page("page-ok"), _make_page("page-404")]
    fake_client = _make_fake_client(pages)

    # Override list_block_children: ok for page-ok, 404 for page-404
    async def fake_list_blocks(block_id, **_kw):
        if block_id == "page-404":
            raise ClientResponseError(
                request_info=MagicMock(), history=(), status=404
            )
        return {"results": [], "has_more": False, "next_cursor": None}

    fake_client.list_block_children = fake_list_blocks

    adapter = _make_adapter(client=fake_client)
    await adapter.prepare()

    items = []
    share_revoked_count = 0
    async for item in adapter.discover():
        if item.extra.get("_skip_reason") == "share_revoked":
            share_revoked_count += 1
        else:
            items.append(item)

    # page-ok should come through, page-404 should be skipped with share_revoked
    assert share_revoked_count == 1
    assert any(i.source_native_id == "page-ok" for i in items)
