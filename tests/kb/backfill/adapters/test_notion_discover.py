"""Tests for NotionBackfillAdapter.discover() — Tasks 4, 5, 6.

Task 4 — search-based root page enumeration + since/until cut:
- test_search_paginates_and_cuts_until
- test_search_stops_when_older_than_since

Task 5 — block tree flattening:
- test_block_tree_flatten_all_types
- test_block_tree_depth_capped_at_8
- test_child_page_block_not_recursed
- test_child_database_queues_db_id

Task 6 — Database handling:
- test_database_meta_emits_index_page
- test_database_rows_via_query
- test_inline_child_database_in_page_queues_rows
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from breadmind.kb.backfill.adapters.notion import (
    NotionBackfillAdapter,
    _flatten_blocks,
    _render_block,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _make_page(
    page_id: str,
    *,
    last_edited: str = "2026-03-01T00:00:00Z",
    created: str = "2026-01-01T00:00:00Z",
    parent_type: str = "workspace",
) -> dict[str, Any]:
    parent: dict[str, Any]
    if parent_type == "workspace":
        parent = {"type": "workspace", "workspace": True}
    elif parent_type.startswith("page:"):
        pid = parent_type[5:]
        parent = {"type": "page_id", "page_id": pid}
    elif parent_type.startswith("db:"):
        did = parent_type[3:]
        parent = {"type": "database_id", "database_id": did}
    else:
        parent = {"type": "workspace", "workspace": True}

    return {
        "object": "page",
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "created_time": created,
        "last_edited_time": last_edited,
        "archived": False,
        "in_trash": False,
        "parent": parent,
        "properties": {
            "title": {
                "id": "title",
                "type": "title",
                "title": [{"plain_text": f"Page {page_id}"}],
            }
        },
        "created_by": {"id": "user-1"},
    }


def _make_db(db_id: str, *, last_edited: str = "2026-03-01T00:00:00Z") -> dict[str, Any]:
    return {
        "object": "database",
        "id": db_id,
        "url": f"https://notion.so/{db_id}",
        "created_time": "2026-01-01T00:00:00Z",
        "last_edited_time": last_edited,
        "archived": False,
        "in_trash": False,
        "parent": {"type": "workspace", "workspace": True},
        "title": [{"plain_text": f"DB {db_id}"}],
        "description": [],
        "properties": {"Name": {"type": "title"}, "Status": {"type": "select"}},
        "created_by": {"id": "user-1"},
    }


def _make_adapter(
    *,
    since: str = "2026-01-01T00:00:00Z",
    until: str = "2026-05-01T00:00:00Z",
    client: Any = None,
) -> NotionBackfillAdapter:
    return NotionBackfillAdapter(
        org_id=_ORG_ID,
        source_filter={"workspace": "test-ws"},
        since=_dt(since),
        until=_dt(until),
        dry_run=True,
        token_budget=1_000_000,
        client=client,
    )


def _build_client(search_pages: list, *, blocks_resp: dict | None = None) -> MagicMock:
    """Build a fake NotionClient."""
    client = MagicMock()
    client.request = AsyncMock(
        return_value={"object": "user", "id": "u1", "bot": {"workspace_id": "ws-1"}}
    )

    # search returns pages
    async def fake_search(filter=None, sort=None, start_cursor=None, page_size=100):
        if start_cursor is None:
            return {
                "results": search_pages,
                "has_more": False,
                "next_cursor": None,
            }
        return {"results": [], "has_more": False, "next_cursor": None}

    client.search = AsyncMock(side_effect=fake_search)

    # list_block_children returns empty by default (no body)
    default_blocks = blocks_resp or {"results": [], "has_more": False, "next_cursor": None}
    client.list_block_children = AsyncMock(return_value=default_blocks)
    client.query_database = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )
    client.close = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Task 4: search pagination + since/until cut
# ---------------------------------------------------------------------------


async def test_search_paginates_and_cuts_until():
    """Pages outside [since, until) must be excluded."""
    since = "2026-02-01T00:00:00Z"
    until = "2026-04-01T00:00:00Z"
    # 3 pages: 1 before since, 1 in window, 1 in window
    pages = [
        _make_page("page-in-1", last_edited="2026-03-15T00:00:00Z"),
        _make_page("page-in-2", last_edited="2026-02-10T00:00:00Z"),
        _make_page("page-out-old", last_edited="2026-01-15T00:00:00Z"),  # < since
    ]
    client = _build_client(pages)
    adapter = _make_adapter(since=since, until=until, client=client)
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset(p["id"] for p in pages)

    items = [item async for item in adapter.discover()]
    ids = [i.source_native_id for i in items if not i.extra.get("_skip_reason")]
    assert "page-in-1" in ids
    assert "page-in-2" in ids
    assert "page-out-old" not in ids


async def test_search_stops_when_older_than_since():
    """When the search response has an item older than since, further pagination
    should stop (search is sorted desc by last_edited_time)."""
    since = "2026-03-01T00:00:00Z"
    until = "2026-05-01T00:00:00Z"

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

    search_calls: list[str | None] = []

    async def fake_search(filter=None, sort=None, start_cursor=None, page_size=100):
        search_calls.append(start_cursor)
        if start_cursor is None:
            return {
                "results": [
                    _make_page("page-ok", last_edited="2026-04-01T00:00:00Z"),
                    _make_page("page-old", last_edited="2026-02-01T00:00:00Z"),
                ],
                "has_more": True,
                "next_cursor": "cursor-2",
            }
        # This second page should NOT be fetched because we stopped
        return {
            "results": [_make_page("page-after-stop", last_edited="2026-04-02T00:00:00Z")],
            "has_more": False,
            "next_cursor": None,
        }

    client.search = AsyncMock(side_effect=fake_search)

    adapter = _make_adapter(since=since, until=until, client=client)
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset(["page-ok", "page-old", "page-after-stop"])

    items = [item async for item in adapter.discover()]
    # Should have stopped before fetching cursor-2
    assert len(search_calls) == 1
    ids = [i.source_native_id for i in items if not i.extra.get("_skip_reason")]
    assert "page-ok" in ids
    assert "page-after-stop" not in ids


async def test_discover_sets_parent_ref_for_subpage():
    """Page with parent.type=page_id should have parent_ref set."""
    pages = [
        _make_page("child-page", parent_type="page:parent-123", last_edited="2026-03-01T00:00:00Z"),
    ]
    client = _build_client(pages)
    adapter = _make_adapter(client=client)
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset(["child-page"])

    items = [item async for item in adapter.discover()]
    real_items = [i for i in items if not i.extra.get("_skip_reason") and not i.extra.get("_fetch_error")]
    assert len(real_items) == 1
    assert real_items[0].parent_ref == "notion_page:parent-123"


# ---------------------------------------------------------------------------
# Task 5: block tree flattening
# ---------------------------------------------------------------------------


def _block(btype: str, **kwargs) -> dict[str, Any]:
    """Build a minimal Notion block dict."""
    rich = kwargs.get("rich_text", [{"plain_text": f"{btype} text"}])
    data = {"rich_text": rich, **{k: v for k, v in kwargs.items() if k != "rich_text"}}
    return {
        "id": f"blk-{btype}",
        "type": btype,
        "has_children": False,
        btype: data,
    }


async def test_block_tree_flatten_all_types():
    """All §3.2 block types must produce expected markdown output."""
    client = MagicMock()
    client.list_block_children = AsyncMock(return_value={"results": [], "has_more": False})

    async def render(btype: str, **kwargs) -> str:
        blk = _block(btype, **kwargs)
        return await _render_block(client, blk, depth=0)

    # paragraph
    assert "paragraph text" in await render("paragraph")

    # headings
    h1 = await render("heading_1")
    assert h1.startswith("# ")

    h2 = await render("heading_2")
    assert h2.startswith("## ")

    h3 = await render("heading_3")
    assert h3.startswith("### ")

    # bulleted list item
    bul = await render("bulleted_list_item")
    assert bul.startswith("- ")

    # numbered list item
    num = await render("numbered_list_item")
    assert num.startswith("1. ")

    # to_do unchecked
    todo_unc = await render("to_do", checked=False)
    assert "[ ]" in todo_unc

    # to_do checked
    todo_c = await render("to_do", checked=True)
    assert "[x]" in todo_c

    # code block with language
    code_blk = await render("code", language="python")
    assert "```python" in code_blk

    # toggle
    toggle_blk = await render("toggle")
    assert "toggle text" in toggle_blk

    # quote
    q = await render("quote")
    assert q.startswith("> ")

    # callout
    cal = await render("callout")
    assert "callout text" in cal

    # equation
    eq = _block("equation")
    eq["equation"] = {"expression": "E=mc^2"}
    eq.pop(eq.get("type") or "equation", None)
    # rebuild properly
    eq2 = {"id": "blk-eq", "type": "equation", "has_children": False, "equation": {"expression": "E=mc^2"}}
    eq_out = await _render_block(client, eq2, depth=0)
    assert "$$E=mc^2$$" in eq_out

    # divider → empty
    div_out = await render("divider")
    assert div_out == ""

    # image → placeholder
    img_blk = {
        "id": "blk-img",
        "type": "image",
        "has_children": False,
        "image": {"type": "external", "external": {"url": "http://x"}, "caption": []},
    }
    img_out = await _render_block(client, img_blk, depth=0)
    assert "[file:" in img_out

    # file placeholder
    file_blk = {
        "id": "blk-file",
        "type": "file",
        "has_children": False,
        "file": {"type": "external", "caption": [{"plain_text": "my_doc.pdf"}]},
    }
    file_out = await _render_block(client, file_blk, depth=0)
    assert "[file: my_doc.pdf]" in file_out

    # table_row → pipe table
    tr_blk = {
        "id": "blk-tr",
        "type": "table_row",
        "has_children": False,
        "table_row": {"cells": [
            [{"plain_text": "A"}],
            [{"plain_text": "B"}],
        ]},
    }
    tr_out = await _render_block(client, tr_blk, depth=0)
    assert "| A | B |" in tr_out

    # child_page → empty (not recursed)
    cp_blk = {
        "id": "blk-cp",
        "type": "child_page",
        "has_children": False,
        "child_page": {"title": "Sub"},
    }
    cp_out = await _render_block(client, cp_blk, depth=0)
    assert cp_out == ""

    # bookmark placeholder
    bm_blk = {
        "id": "blk-bm",
        "type": "bookmark",
        "has_children": False,
        "bookmark": {"url": "https://example.com", "caption": []},
    }
    bm_out = await _render_block(client, bm_blk, depth=0)
    assert "[file:" in bm_out


async def test_block_tree_depth_capped_at_8():
    """Block fetching stops at depth 8; truncation marker appears."""
    from breadmind.kb.backfill.adapters.notion import _DEPTH_TRUNCATION_MARKER

    client = MagicMock()
    client.list_block_children = AsyncMock(return_value={"results": [], "has_more": False})

    result = await _flatten_blocks(client, "root-id", depth=_MAX_DEPTH)
    assert _DEPTH_TRUNCATION_MARKER in result


_MAX_DEPTH = 8


async def test_child_page_block_not_recursed():
    """child_page blocks should produce no text (separate discover entry)."""
    client = MagicMock()
    client.list_block_children = AsyncMock(return_value={"results": [], "has_more": False})
    blk = {
        "id": "blk-cp",
        "type": "child_page",
        "has_children": True,
        "child_page": {"title": "Nested"},
    }
    result = await _render_block(client, blk, depth=0)
    assert result == ""
    # list_block_children should NOT have been called for child_page
    client.list_block_children.assert_not_called()


async def test_child_database_queues_db_id():
    """child_database blocks should add their ID to db_queue."""
    client = MagicMock()
    client.list_block_children = AsyncMock(return_value={"results": [], "has_more": False})
    blk = {
        "id": "child-db-99",
        "type": "child_database",
        "has_children": False,
        "child_database": {"title": "Inline DB"},
    }
    queue: list[str] = []
    result = await _render_block(client, blk, depth=0, db_queue=queue)
    assert result == ""
    assert "child-db-99" in queue


# ---------------------------------------------------------------------------
# Task 6: Database handling
# ---------------------------------------------------------------------------


async def test_database_meta_emits_index_page():
    """search result with object=database should emit a DB index BackfillItem."""
    db = _make_db("db-001", last_edited="2026-03-01T00:00:00Z")
    client = _build_client([db])
    # No rows
    client.query_database = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )
    adapter = _make_adapter(client=client)
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset()

    items = [item async for item in adapter.discover()]
    db_items = [i for i in items if i.source_kind == "notion_database"]
    assert len(db_items) >= 1
    assert db_items[0].source_native_id == "db-001"
    assert "[DB]" in db_items[0].title


async def test_database_rows_via_query():
    """DB rows from databases.query should be yielded as BackfillItems with
    parent_ref pointing to the parent DB."""
    db = _make_db("db-002", last_edited="2026-03-01T00:00:00Z")
    row = _make_page("row-001", last_edited="2026-03-02T00:00:00Z", parent_type="db:db-002")

    client = _build_client([db])
    client.query_database = AsyncMock(
        return_value={"results": [row], "has_more": False, "next_cursor": None}
    )
    # rows also have blocks fetched
    client.list_block_children = AsyncMock(
        return_value={"results": [], "has_more": False, "next_cursor": None}
    )

    adapter = _make_adapter(client=client)
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset()

    items = [item async for item in adapter.discover()]
    row_items = [i for i in items if i.source_native_id == "row-001"]
    assert len(row_items) == 1
    assert row_items[0].parent_ref == "notion_database:db-002"


async def test_inline_child_database_in_page_queues_rows():
    """A child_database block inside a page's body should cause rows to be
    enumerated via databases.query."""
    page = _make_page("page-with-inline-db", last_edited="2026-03-01T00:00:00Z")
    row = _make_page("inline-row-001", last_edited="2026-03-02T00:00:00Z")

    client = MagicMock()
    client.request = AsyncMock(
        return_value={"object": "user", "id": "u1", "bot": {"workspace_id": "ws-1"}}
    )
    client.close = AsyncMock()

    async def fake_search(**_kw):
        return {"results": [page], "has_more": False, "next_cursor": None}

    client.search = AsyncMock(side_effect=fake_search)

    child_db_block = {
        "id": "inline-db-blk-001",
        "type": "child_database",
        "has_children": False,
        "child_database": {"title": "Inline DB"},
    }

    async def fake_list_blocks(block_id, **_kw):
        if block_id == "page-with-inline-db":
            return {
                "results": [child_db_block],
                "has_more": False,
                "next_cursor": None,
            }
        return {"results": [], "has_more": False, "next_cursor": None}

    client.list_block_children = AsyncMock(side_effect=fake_list_blocks)

    async def fake_query_db(db_id, **_kw):
        if db_id == "inline-db-blk-001":
            return {"results": [row], "has_more": False, "next_cursor": None}
        return {"results": [], "has_more": False, "next_cursor": None}

    client.query_database = AsyncMock(side_effect=fake_query_db)

    adapter = _make_adapter(client=client)
    adapter._workspace_id = "ws-1"
    adapter._share_in_snapshot = frozenset(["page-with-inline-db", "inline-row-001"])

    items = [item async for item in adapter.discover()]
    page_ids = [i.source_native_id for i in items]
    assert "inline-row-001" in page_ids
