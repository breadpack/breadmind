"""Tests for personal assistant LLM tool functions."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_adapter_registry():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.create_item = AsyncMock(return_value="new-task-id")
    task_adapter.list_items = AsyncMock(return_value=[])
    task_adapter.update_item = AsyncMock(return_value=True)
    task_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(task_adapter)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.create_item = AsyncMock(return_value="new-event-id")
    event_adapter.list_items = AsyncMock(return_value=[])
    event_adapter.update_item = AsyncMock(return_value=True)
    event_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(event_adapter)

    return registry


@pytest.mark.asyncio
async def test_task_create(mock_adapter_registry):
    from breadmind.personal.tools import task_create
    result = await task_create(title="Buy milk", registry=mock_adapter_registry, user_id="alice")
    assert "new-task-id" in result


@pytest.mark.asyncio
async def test_task_list_empty(mock_adapter_registry):
    from breadmind.personal.tools import task_list
    result = await task_list(registry=mock_adapter_registry, user_id="alice")
    assert "없습니다" in result


@pytest.mark.asyncio
async def test_task_update(mock_adapter_registry):
    from breadmind.personal.tools import task_update
    result = await task_update(task_id="t1", status="done", registry=mock_adapter_registry)
    assert "업데이트" in result or "완료" in result


@pytest.mark.asyncio
async def test_task_delete(mock_adapter_registry):
    from breadmind.personal.tools import task_delete
    result = await task_delete(task_id="t1", registry=mock_adapter_registry)
    assert "삭제" in result


@pytest.mark.asyncio
async def test_event_create(mock_adapter_registry):
    from breadmind.personal.tools import event_create
    result = await event_create(title="Standup", start_at="2026-03-18T09:00:00Z",
        registry=mock_adapter_registry, user_id="alice")
    assert "new-event-id" in result


@pytest.mark.asyncio
async def test_event_list(mock_adapter_registry):
    from breadmind.personal.tools import event_list
    result = await event_list(registry=mock_adapter_registry, user_id="alice")
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_reminder_set(mock_adapter_registry):
    from breadmind.personal.tools import reminder_set
    result = await reminder_set(message="Take medicine", remind_at="2026-03-18T18:00:00Z",
        registry=mock_adapter_registry, user_id="alice")
    mock_adapter_registry.get_adapter("event", "builtin").create_item.assert_called_once()
    assert "리마인더" in result
