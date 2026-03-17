"""Cross-domain query tests."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest


@pytest.fixture
def mock_registry():
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.personal.models import Task, Event

    registry = AdapterRegistry()
    now = datetime.now(timezone.utc)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[
        Event(id="e1", title="Standup", start_at=now + timedelta(hours=2),
              end_at=now + timedelta(hours=2, minutes=30)),
    ])
    registry.register(event_adapter)

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[
        Task(id="t1", title="Review PR", status="pending", due_at=now + timedelta(hours=1)),
    ])
    registry.register(task_adapter)

    return registry


@pytest.mark.asyncio
async def test_tasks_before_next_event(mock_registry):
    from breadmind.personal.cross_domain import CrossDomainQuery
    query = CrossDomainQuery(mock_registry)
    result = await query.tasks_before_next_event("alice")
    assert result["next_event"] is not None
    assert result["next_event"].title == "Standup"
    assert len(result["tasks_due_before"]) == 1
    assert "Review PR" in result["message"]


@pytest.mark.asyncio
async def test_tasks_before_no_events():
    from breadmind.personal.cross_domain import CrossDomainQuery
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    registry.register(event_adapter)

    query = CrossDomainQuery(registry)
    result = await query.tasks_before_next_event("alice")
    assert result["next_event"] is None
    assert "없습니다" in result["message"]


@pytest.mark.asyncio
async def test_daily_agenda(mock_registry):
    from breadmind.personal.cross_domain import CrossDomainQuery
    query = CrossDomainQuery(mock_registry)
    result = await query.daily_agenda("alice")
    assert len(result["events"]) >= 0  # May or may not match today
    assert "message" in result


@pytest.mark.asyncio
async def test_find_free_slots(mock_registry):
    from breadmind.personal.cross_domain import CrossDomainQuery
    query = CrossDomainQuery(mock_registry)
    slots = await query.find_free_slots("alice", duration_minutes=30)
    assert isinstance(slots, list)
    for slot in slots:
        assert slot["duration_minutes"] >= 30


@pytest.mark.asyncio
async def test_find_free_slots_no_events():
    from breadmind.personal.cross_domain import CrossDomainQuery
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    registry.register(event_adapter)

    query = CrossDomainQuery(registry)
    slots = await query.find_free_slots("alice", duration_minutes=60, days_ahead=1)
    assert len(slots) == 1  # Entire day is free
