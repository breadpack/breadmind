# tests/test_builtin_event_adapter.py
"""BuiltinEventAdapter unit tests."""
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
async def test_create_event(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
    from breadmind.personal.models import Event
    db, conn = mock_db
    conn.fetchrow.return_value = {"id": "00000000-0000-0000-0000-000000000001"}
    adapter = BuiltinEventAdapter(db)
    now = datetime.now(timezone.utc)
    event = Event(id="", title="Standup", start_at=now, end_at=now + timedelta(minutes=30), user_id="alice")
    result_id = await adapter.create_item(event)
    assert result_id is not None


@pytest.mark.asyncio
async def test_list_events_time_range(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
    db, conn = mock_db
    now = datetime.now(timezone.utc)
    conn.fetch.return_value = [
        {"id": "e1", "title": "Meeting", "description": None, "start_at": now,
         "end_at": now + timedelta(hours=1), "all_day": False, "location": None,
         "attendees": [], "reminder_minutes": [15], "recurrence": None,
         "source": "builtin", "source_id": None, "user_id": "alice", "created_at": now},
    ]
    adapter = BuiltinEventAdapter(db)
    events = await adapter.list_items(filters={"user_id": "alice", "start_after": now, "start_before": now + timedelta(days=7)})
    assert len(events) == 1
    assert events[0].title == "Meeting"


@pytest.mark.asyncio
async def test_update_event(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
    db, conn = mock_db
    adapter = BuiltinEventAdapter(db)
    result = await adapter.update_item("e1", {"title": "Updated Meeting", "location": "Room A"})
    assert result is True


@pytest.mark.asyncio
async def test_delete_event(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
    db, conn = mock_db
    adapter = BuiltinEventAdapter(db)
    result = await adapter.delete_item("e1")
    assert result is True
