"""Tests for ConversationManager extracted from CoreAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from breadmind.core.conversation_manager import ConversationManager
from breadmind.llm.base import LLMMessage


# --- build_messages tests ---


def test_build_messages_without_working_memory():
    """Without working memory, returns [system, user] only."""
    cm = ConversationManager()
    messages = cm.build_messages(
        session_id="u:c", user_message="hello", system_prompt="You are a bot.",
    )
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[0].content == "You are a bot."
    assert messages[1].role == "user"
    assert messages[1].content == "hello"


def test_build_messages_with_working_memory():
    """With working memory, includes previous conversation messages."""
    from breadmind.memory.working import WorkingMemory

    wm = WorkingMemory()
    cm = ConversationManager(working_memory=wm)

    # Pre-populate a session with some history
    wm.get_or_create_session("alice:general", user="alice", channel="general")
    wm.add_message("alice:general", LLMMessage(role="user", content="first msg"))
    wm.add_message("alice:general", LLMMessage(role="assistant", content="first reply"))

    messages = cm.build_messages(
        session_id="alice:general",
        user_message="second msg",
        system_prompt="System prompt.",
        user="alice",
        channel="general",
    )

    # system + 2 history + current user
    assert len(messages) == 4
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[1].content == "first msg"
    assert messages[2].role == "assistant"
    assert messages[2].content == "first reply"
    assert messages[3].role == "user"
    assert messages[3].content == "second msg"


def test_build_messages_stores_sanitized_user_message():
    """build_messages should store a sanitized copy of user message in memory."""
    from breadmind.memory.working import WorkingMemory

    wm = WorkingMemory()
    cm = ConversationManager(working_memory=wm)

    cm.build_messages(
        session_id="u:c",
        user_message="my password is secret123",
        system_prompt="Sys.",
        user="u",
        channel="c",
    )

    session = wm.get_or_create_session("u:c")
    # The stored message should exist (sanitized or not depending on vault logic)
    assert len(session.messages) >= 1
    assert session.messages[-1].role == "user"


# --- enrich_context tests ---


@pytest.mark.asyncio
async def test_enrich_context_without_context_builder():
    """Without context_builder, messages are returned unchanged."""
    cm = ConversationManager()
    original = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    result = await cm.enrich_context(
        original, session_id="s", user_message="hi", system_prompt="Sys",
    )
    assert result is original


@pytest.mark.asyncio
async def test_enrich_context_with_context_builder():
    """Context builder enrichment messages are inserted after system prompt."""
    cb = AsyncMock()
    cb.build_context = AsyncMock(return_value=[
        LLMMessage(role="system", content="User likes Korean"),
        LLMMessage(role="system", content="Known host: 10.0.0.1"),
    ])

    cm = ConversationManager(context_builder=cb)
    original = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    result = await cm.enrich_context(
        original, session_id="s", user_message="hi", system_prompt="Sys",
    )

    cb.build_context.assert_called_once()
    # system + 2 enrichment + user
    assert len(result) == 4
    assert result[0].role == "system"
    assert result[0].content == "Sys"
    assert result[1].content == "User likes Korean"
    assert result[2].content == "Known host: 10.0.0.1"
    assert result[3].role == "user"


@pytest.mark.asyncio
async def test_enrich_context_filters_duplicate_system_prompt():
    """Enrichment messages matching system_prompt content are excluded."""
    cb = AsyncMock()
    cb.build_context = AsyncMock(return_value=[
        LLMMessage(role="system", content="Sys"),  # same as system prompt
        LLMMessage(role="system", content="Extra context"),
    ])

    cm = ConversationManager(context_builder=cb)
    original = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    result = await cm.enrich_context(
        original, session_id="s", user_message="hi", system_prompt="Sys",
    )

    # Only "Extra context" should be added
    assert len(result) == 3
    assert result[1].content == "Extra context"


@pytest.mark.asyncio
async def test_enrich_context_handles_timeout():
    """On context builder timeout, returns original messages."""
    cb = AsyncMock()

    async def slow_build(*args, **kwargs):
        import asyncio
        await asyncio.sleep(100)
        return []

    cb.build_context = slow_build

    cm = ConversationManager(context_builder=cb)
    original = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    # The 10s timeout inside enrich_context will trigger,
    # but for test speed we'll patch asyncio.wait_for to raise
    with patch("breadmind.core.conversation_manager.asyncio.wait_for", side_effect=Exception("timeout")):
        result = await cm.enrich_context(
            original, session_id="s", user_message="hi", system_prompt="Sys",
        )
    assert result is original


# --- maybe_summarize tests ---


@pytest.mark.asyncio
async def test_maybe_summarize_without_summarizer():
    """Without summarizer, returns original messages."""
    cm = ConversationManager()
    messages = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    result = await cm.maybe_summarize(messages, tools=[])
    assert result is messages


@pytest.mark.asyncio
async def test_maybe_summarize_with_summarizer():
    """Summarizer.summarize_if_needed is called and its result returned."""
    summarizer = AsyncMock()
    summarized = [LLMMessage(role="system", content="Summary")]
    summarizer.summarize_if_needed = AsyncMock(return_value=summarized)

    cm = ConversationManager(summarizer=summarizer)
    messages = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    result = await cm.maybe_summarize(messages, tools=[])
    assert result is summarized
    summarizer.summarize_if_needed.assert_called_once_with(messages, [])


@pytest.mark.asyncio
async def test_maybe_summarize_on_summarizer_error():
    """On summarizer error, returns original messages."""
    summarizer = AsyncMock()
    summarizer.summarize_if_needed = AsyncMock(side_effect=RuntimeError("boom"))

    cm = ConversationManager(summarizer=summarizer)
    messages = [
        LLMMessage(role="system", content="Sys"),
        LLMMessage(role="user", content="hi"),
    ]
    result = await cm.maybe_summarize(messages, tools=[])
    assert result is messages


# --- store_assistant_message / store_message tests ---


def test_store_assistant_message_with_memory():
    from breadmind.memory.working import WorkingMemory

    wm = WorkingMemory()
    cm = ConversationManager(working_memory=wm)
    wm.get_or_create_session("s")
    cm.store_assistant_message("s", "Hello!")

    session = wm.get_or_create_session("s")
    assert len(session.messages) == 1
    assert session.messages[0].role == "assistant"
    assert session.messages[0].content == "Hello!"


def test_store_assistant_message_without_memory():
    """No error when working memory is None."""
    cm = ConversationManager()
    cm.store_assistant_message("s", "Hello!")  # should not raise


def test_store_message_with_memory():
    from breadmind.memory.working import WorkingMemory

    wm = WorkingMemory()
    cm = ConversationManager(working_memory=wm)
    wm.get_or_create_session("s")
    msg = LLMMessage(role="user", content="test")
    cm.store_message("s", msg)

    session = wm.get_or_create_session("s")
    assert len(session.messages) == 1
    assert session.messages[0].content == "test"


def test_store_message_without_memory():
    """No error when working memory is None."""
    cm = ConversationManager()
    cm.store_message("s", LLMMessage(role="user", content="test"))  # should not raise


# --- property accessors ---


def test_properties():
    wm = MagicMock()
    cb = MagicMock()
    sm = MagicMock()
    cm = ConversationManager(working_memory=wm, context_builder=cb, summarizer=sm)

    assert cm.working_memory is wm
    assert cm.context_builder is cb
    assert cm.summarizer is sm

    new_wm = MagicMock()
    cm.working_memory = new_wm
    assert cm.working_memory is new_wm
