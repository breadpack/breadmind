"""T8: CoreAgent end-of-turn user-message signal hook."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from breadmind.llm.base import LLMMessage, ToolCall
from breadmind.memory.event_types import SignalKind


async def _drain_pending_tasks():
    """Yield to the event loop so fire-and-forget tasks scheduled by the agent
    have a chance to run before assertions."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_user_correction_after_tool_run_emits_signal(make_agent):
    """When the previous turn ran a tool and the user replies with a correction
    phrase, the agent emits a USER_CORRECTION SignalEvent to the recorder."""
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    # Step 1: user asks tool; we simulate that by writing an assistant tool-call
    # turn + tool result into working memory directly so the next user message
    # finds `last_tool_name` already populated.
    session_id = "alice:general"
    agent._working_memory.get_or_create_session(
        session_id, user="alice", channel="general",
    )
    agent._working_memory.add_message(
        session_id,
        LLMMessage(role="user", content="VPC를 ap-northeast-2에 만들어줘"),
    )
    agent._working_memory.add_message(
        session_id,
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="tc1", name="aws_vpc_create", arguments={})],
        ),
    )
    agent._working_memory.add_message(
        session_id,
        LLMMessage(
            role="tool",
            content="vpc-123 created",
            tool_call_id="tc1",
            name="aws_vpc_create",
        ),
    )

    # Step 2: user corrects
    await agent.handle_message(
        "아니, 다시 해줘", user="alice", channel="general",
    )
    await _drain_pending_tasks()

    kinds = [c.args[0].kind for c in rec.record.await_args_list]
    assert SignalKind.USER_CORRECTION in kinds


@pytest.mark.asyncio
async def test_explicit_pin_emits_signal(make_agent):
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    await agent.handle_message(
        "기억해줘: API key는 vault X에 있다",
        user="bob",
        channel="general",
    )
    await _drain_pending_tasks()

    kinds = [c.args[0].kind for c in rec.record.await_args_list]
    assert SignalKind.EXPLICIT_PIN in kinds


@pytest.mark.asyncio
async def test_chitchat_does_not_emit_signal(make_agent):
    """Plain greetings should not trigger any signal."""
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    await agent.handle_message("안녕", user="carol", channel="general")
    await _drain_pending_tasks()

    rec.record.assert_not_called()


@pytest.mark.asyncio
async def test_no_recorder_is_safe(make_agent):
    """When `episodic_recorder` is None, `handle_message` must still complete."""
    agent = make_agent(recorder=None)

    result = await agent.handle_message(
        "기억해줘: this should not crash anything",
        user="dave",
        channel="general",
    )
    # No recorder, no error. Provider stub returns "ok".
    assert result == "ok"


@pytest.mark.asyncio
async def test_recorder_failure_does_not_break_turn(make_agent):
    """A recorder that raises must not bubble into the user's turn."""
    rec = AsyncMock()
    rec.record.side_effect = RuntimeError("boom")
    agent = make_agent(recorder=rec)

    result = await agent.handle_message(
        "기억해줘 이거",
        user="eve",
        channel="general",
    )
    await _drain_pending_tasks()

    # The turn returned cleanly.
    assert result == "ok"
    # Recorder was invoked at least once (raised internally; agent absorbed it).
    assert rec.record.await_count >= 1
