"""Tests for ContextProvider plugin pattern and PersonalContextProvider."""
from unittest.mock import AsyncMock, MagicMock
import pytest


def test_context_builder_accepts_providers():
    from breadmind.memory.context_builder import ContextBuilder
    cb = ContextBuilder(working_memory=MagicMock())
    assert hasattr(cb, "register_provider")


@pytest.mark.asyncio
async def test_personal_context_provider_schedule_intent():
    from breadmind.personal.context_provider import PersonalContextProvider
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.core.intent import IntentCategory

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

    provider = PersonalContextProvider(registry)
    intent = MagicMock()
    intent.category = IntentCategory.SCHEDULE

    messages = await provider.get_context("session1", "내일 회의", intent)
    assert isinstance(messages, list)
    event_adapter.list_items.assert_called_once()
    task_adapter.list_items.assert_called_once()


@pytest.mark.asyncio
async def test_personal_context_provider_chat_intent_noop():
    from breadmind.personal.context_provider import PersonalContextProvider
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.core.intent import IntentCategory

    registry = AdapterRegistry()
    provider = PersonalContextProvider(registry)
    intent = MagicMock()
    intent.category = IntentCategory.CHAT

    messages = await provider.get_context("session1", "안녕하세요", intent)
    assert messages == []
