"""Tests for the Notion adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.personal.adapters.notion import NotionAdapter, _page_to_task
from breadmind.personal.models import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_page(
    page_id: str = "page-1",
    title: str = "Buy groceries",
    status: str = "Not started",
    priority: str = "High",
    due: str | None = "2026-04-01",
) -> dict:
    """Return a minimal Notion page object."""
    props: dict = {
        "Title": {"title": [{"plain_text": title}]},
        "Status": {"status": {"name": status}},
        "Priority": {"select": {"name": priority}},
    }
    if due:
        props["Due date"] = {"date": {"start": due}}
    return {"id": page_id, "properties": props}


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    """Create a mock aiohttp response as an async context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    resp.raise_for_status = MagicMock()
    return resp


def _patch_session(adapter: NotionAdapter, response: AsyncMock) -> None:
    """Inject a mock session whose .request() returns *response*."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    session.closed = False
    adapter._session = session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success():
    adapter = NotionAdapter(database_id="db-1")
    user_resp = _mock_response({"id": "user-1", "type": "bot"})
    _patch_session(adapter, user_resp)

    result = await adapter.authenticate({"api_key": "secret-key"})

    assert result is True
    assert adapter._api_key == "secret-key"


@pytest.mark.asyncio
async def test_authenticate_failure():
    adapter = NotionAdapter(database_id="db-1")
    fail_resp = _mock_response({}, status=401)
    fail_resp.raise_for_status = MagicMock(
        side_effect=Exception("Unauthorized")
    )
    _patch_session(adapter, fail_resp)

    result = await adapter.authenticate({"api_key": "bad-key"})

    assert result is False
    assert adapter._api_key is None


@pytest.mark.asyncio
async def test_list_items():
    adapter = NotionAdapter(database_id="db-1")
    adapter._api_key = "key"

    page = _make_page()
    query_resp = _mock_response({"results": [page]})
    _patch_session(adapter, query_resp)

    tasks = await adapter.list_items()

    assert len(tasks) == 1
    assert isinstance(tasks[0], Task)
    assert tasks[0].title == "Buy groceries"
    assert tasks[0].status == "pending"
    assert tasks[0].priority == "high"
    assert tasks[0].source == "notion"
    assert tasks[0].source_id == "page-1"

    # Verify the correct endpoint was called.
    session = adapter._session
    session.request.assert_called_once()
    call_args = session.request.call_args
    assert call_args[0][0] == "POST"
    assert "/databases/db-1/query" in call_args[0][1]


@pytest.mark.asyncio
async def test_create_item():
    adapter = NotionAdapter(database_id="db-1")
    adapter._api_key = "key"

    created_resp = _mock_response({"id": "new-page-id"})
    _patch_session(adapter, created_resp)

    task = Task(
        id="local-1",
        title="Write report",
        status="in_progress",
        priority="high",
        due_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    page_id = await adapter.create_item(task)

    assert page_id == "new-page-id"
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "POST"
    assert "/pages" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["parent"]["database_id"] == "db-1"
    assert body["properties"]["Title"]["title"][0]["text"]["content"] == "Write report"


@pytest.mark.asyncio
async def test_update_item():
    adapter = NotionAdapter(database_id="db-1")
    adapter._api_key = "key"

    update_resp = _mock_response({"id": "page-1"})
    _patch_session(adapter, update_resp)

    result = await adapter.update_item(
        "page-1", {"title": "Updated title", "status": "done"}
    )

    assert result is True
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "PATCH"
    assert "/pages/page-1" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["properties"]["Title"]["title"][0]["text"]["content"] == "Updated title"
    assert body["properties"]["Status"]["status"]["name"] == "Done"


@pytest.mark.asyncio
async def test_delete_item():
    adapter = NotionAdapter(database_id="db-1")
    adapter._api_key = "key"

    archive_resp = _mock_response({"id": "page-1", "archived": True})
    _patch_session(adapter, archive_resp)

    result = await adapter.delete_item("page-1")

    assert result is True
    session = adapter._session
    call_args = session.request.call_args
    assert call_args[0][0] == "PATCH"
    assert "/pages/page-1" in call_args[0][1]
    body = call_args[1]["json"]
    assert body["archived"] is True


@pytest.mark.asyncio
async def test_get_item():
    adapter = NotionAdapter(database_id="db-1")
    adapter._api_key = "key"

    page = _make_page(page_id="page-42", title="Specific task")
    get_resp = _mock_response(page)
    _patch_session(adapter, get_resp)

    task = await adapter.get_item("page-42")

    assert isinstance(task, Task)
    assert task.title == "Specific task"
    assert task.source_id == "page-42"


def test_page_to_task_due_date_parsing():
    page = _make_page(due="2026-04-15T10:00:00+00:00")
    task = _page_to_task(page)
    assert task.due_at is not None
    assert task.due_at.year == 2026
    assert task.due_at.month == 4
    assert task.due_at.day == 15


def test_page_to_task_missing_optional_fields():
    page = {"id": "p-1", "properties": {}}
    task = _page_to_task(page)
    assert task.title == ""
    assert task.status == "pending"
    assert task.priority == "medium"
    assert task.due_at is None
