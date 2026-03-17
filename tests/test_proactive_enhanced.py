"""Tests for enhanced proactive suggestions."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_deps():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[])
    registry.register(task_adapter)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    registry.register(event_adapter)

    router = AsyncMock()
    router.broadcast_notification = AsyncMock()
    return registry, router, task_adapter, event_adapter


@pytest.mark.asyncio
async def test_daily_summary(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Task, Event
    registry, router, task_adapter, event_adapter = mock_deps
    now = datetime.now(timezone.utc)

    task_adapter.list_items.return_value = [
        Task(id="t1", title="Review PR", status="pending", due_at=now + timedelta(hours=4)),
    ]
    event_adapter.list_items.return_value = [
        Event(id="e1", title="Standup", start_at=now + timedelta(hours=2),
              end_at=now + timedelta(hours=2, minutes=30)),
    ]

    scheduler = PersonalScheduler(registry, router)
    summary = await scheduler.generate_daily_summary()
    assert "Review PR" in summary
    assert "Standup" in summary


@pytest.mark.asyncio
async def test_overdue_detection(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Task
    registry, router, task_adapter, _ = mock_deps
    now = datetime.now(timezone.utc)

    task_adapter.list_items.return_value = [
        Task(id="t1", title="Overdue task", status="pending",
             due_at=now - timedelta(hours=2)),
    ]

    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_overdue()
    router.broadcast_notification.assert_called_once()
    assert "지연" in router.broadcast_notification.call_args[0][0] or "Overdue" in router.broadcast_notification.call_args[0][0]


@pytest.mark.asyncio
async def test_no_overdue_when_empty(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    registry, router, _, _ = mock_deps
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_overdue()
    router.broadcast_notification.assert_not_called()
