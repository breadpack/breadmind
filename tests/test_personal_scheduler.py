# tests/test_personal_scheduler.py
"""Tests for PersonalScheduler."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_deps():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    registry.register(event_adapter)

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[])
    registry.register(task_adapter)

    router = AsyncMock()
    router.broadcast_notification = AsyncMock()

    return registry, router, event_adapter, task_adapter


@pytest.mark.asyncio
async def test_check_reminders_sends_notification(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Event
    registry, router, event_adapter, _ = mock_deps
    now = datetime.now(timezone.utc)
    upcoming_event = Event(id="e1", title="Meeting",
        start_at=now + timedelta(minutes=10), end_at=now + timedelta(minutes=70),
        reminder_minutes=[15])
    event_adapter.list_items.return_value = [upcoming_event]
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_reminders()
    router.broadcast_notification.assert_called_once()
    assert "Meeting" in router.broadcast_notification.call_args[0][0]


@pytest.mark.asyncio
async def test_check_reminders_no_event(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    registry, router, _, _ = mock_deps
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_reminders()
    router.broadcast_notification.assert_not_called()


@pytest.mark.asyncio
async def test_check_deadlines_sends_warning(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Task
    registry, router, _, task_adapter = mock_deps
    now = datetime.now(timezone.utc)
    overdue_task = Task(id="t1", title="Submit report", due_at=now + timedelta(hours=6), status="pending")
    task_adapter.list_items.return_value = [overdue_task]
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_deadlines()
    router.broadcast_notification.assert_called_once()
    assert "Submit report" in router.broadcast_notification.call_args[0][0]


@pytest.mark.asyncio
async def test_check_deadlines_no_tasks(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    registry, router, _, _ = mock_deps
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_deadlines()
    router.broadcast_notification.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_notification_prevention(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Event
    registry, router, event_adapter, _ = mock_deps
    now = datetime.now(timezone.utc)
    event = Event(id="e1", title="Meeting",
        start_at=now + timedelta(minutes=10), end_at=now + timedelta(minutes=70),
        reminder_minutes=[15])
    event_adapter.list_items.return_value = [event]
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_reminders()
    await scheduler._check_reminders()  # second call
    # Should only notify once due to _notified set
    assert router.broadcast_notification.call_count == 1
