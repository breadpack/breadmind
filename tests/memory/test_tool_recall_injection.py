"""P1 integration: tool-level recall renders into the next LLM turn's prompt.

Verifies that after a tool call inside ``CoreAgent.handle_message``, the
prior_runs system message produced by ``_do_recall`` is appended to the
messages list before the next ``provider.chat`` invocation.
"""
from __future__ import annotations

import copy
from unittest.mock import AsyncMock

import pytest

from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage
from breadmind.storage.models import EpisodicNote


def _make_note(*, summary: str, tool_name: str, outcome: str = "ok") -> EpisodicNote:
    return EpisodicNote(
        content=summary,
        keywords=[],
        tags=[],
        context_description="",
        summary=summary,
        tool_name=tool_name,
        outcome=outcome,
        kind="tool_executed",
    )


@pytest.mark.asyncio
async def test_tool_recall_injects_system_message_into_next_turn(make_agent):
    """The next LLM turn must see a prior_runs system message for the tool."""
    store = AsyncMock()
    store.search.return_value = [
        _make_note(summary="prior-run-A", tool_name="test_tool", outcome="ok"),
        _make_note(summary="prior-run-B", tool_name="test_tool", outcome="failed"),
    ]
    rec = AsyncMock()
    agent = make_agent(recorder=rec, episodic_store=store)

    tool_response = LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="tc_1", name="test_tool", arguments={"input": "hello"})],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="tool_use",
    )
    final_response = LLMResponse(
        content="done",
        tool_calls=[],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="end_turn",
    )
    responses = [tool_response, final_response]
    captured: list[list] = []

    async def _chat(messages, **kwargs):
        # Snapshot messages exactly as the provider sees them.
        captured.append(copy.deepcopy(messages))
        return responses.pop(0)

    agent._provider.chat = _chat

    result = await agent.handle_message(
        "run the tool please", user="frank", channel="general",
    )
    assert result == "done"

    # Two LLM calls were made.
    assert len(captured) == 2

    # The second call (after the tool ran) must include the prior_runs system
    # message generated from the recalled notes.
    second_msgs = captured[1]
    system_msgs = [m for m in second_msgs if getattr(m, "role", None) == "system"]
    assert any(
        "previous_runs_for_test_tool" in (m.content or "")
        and "prior-run-A" in (m.content or "")
        for m in system_msgs
    ), (
        "expected a system message rendered from render_previous_runs_for_tool "
        f"in the second LLM call, got: {[m.content for m in system_msgs]}"
    )

    # And the first call (before the tool ran) must NOT include it.
    first_system = [m for m in captured[0] if getattr(m, "role", None) == "system"]
    assert not any(
        "previous_runs_for_test_tool" in (m.content or "") for m in first_system
    )

    # Buffer cleared after drain.
    assert agent._tool_executor.drain_recall_messages() == []


@pytest.mark.asyncio
async def test_tool_recall_no_notes_no_injection(make_agent):
    """When the store returns no notes, no system message is added."""
    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()
    agent = make_agent(recorder=rec, episodic_store=store)

    tool_response = LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="tc_1", name="test_tool", arguments={"input": "hi"})],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="tool_use",
    )
    final_response = LLMResponse(
        content="done",
        tool_calls=[],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="end_turn",
    )
    responses = [tool_response, final_response]
    captured: list[list] = []

    async def _chat(messages, **kwargs):
        captured.append(copy.deepcopy(messages))
        return responses.pop(0)

    agent._provider.chat = _chat

    result = await agent.handle_message("go", user="grace", channel="general")
    assert result == "done"
    assert len(captured) == 2

    second_system = [m for m in captured[1] if getattr(m, "role", None) == "system"]
    assert not any(
        "previous_runs_for_" in (m.content or "") for m in second_system
    )
