# tests/test_builtin_task_adapter.py
"""BuiltinTaskAdapter unit tests using mock database."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_db():
    db = AsyncMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    class AcquireCM:
        async def __aenter__(self):
            return conn
        async def __aexit__(self, *args):
            pass

    db.acquire = MagicMock(return_value=AcquireCM())
    return db, conn


@pytest.mark.asyncio
async def test_create_task(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    from breadmind.personal.models import Task
    db, conn = mock_db
    conn.fetchrow.return_value = {"id": "00000000-0000-0000-0000-000000000001"}
    adapter = BuiltinTaskAdapter(db)
    task = Task(id="", title="Buy milk", user_id="alice")
    result_id = await adapter.create_item(task)
    assert result_id is not None
    conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_list_tasks_no_filters(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    db, conn = mock_db
    conn.fetch.return_value = [
        {"id": "id1", "title": "Task 1", "description": None, "status": "pending",
         "priority": "medium", "due_at": None, "recurrence": None, "tags": [],
         "source": "builtin", "source_id": None, "assignee": None, "parent_id": None,
         "user_id": "alice", "created_at": datetime.now(timezone.utc),
         "updated_at": datetime.now(timezone.utc)},
    ]
    adapter = BuiltinTaskAdapter(db)
    tasks = await adapter.list_items(filters={"user_id": "alice"})
    assert len(tasks) == 1
    assert tasks[0].title == "Task 1"


@pytest.mark.asyncio
async def test_update_task(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    db, conn = mock_db
    adapter = BuiltinTaskAdapter(db)
    result = await adapter.update_item("task-id-1", {"status": "done", "title": "Updated"})
    assert result is True


@pytest.mark.asyncio
async def test_delete_task(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    db, conn = mock_db
    adapter = BuiltinTaskAdapter(db)
    result = await adapter.delete_item("task-id-1")
    assert result is True


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    db, conn = mock_db
    conn.fetch.return_value = []
    adapter = BuiltinTaskAdapter(db)
    await adapter.list_items(filters={"user_id": "alice", "status": "done"})
    conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_list_tasks_with_due_before_filter(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    db, conn = mock_db
    conn.fetch.return_value = []
    adapter = BuiltinTaskAdapter(db)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    await adapter.list_items(filters={"user_id": "alice", "due_before": tomorrow})
    conn.fetch.assert_called_once()
