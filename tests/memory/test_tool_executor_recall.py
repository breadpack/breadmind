"""T9: ToolExecutor pre-call recall + post-call signal.

T9.5 adds integration tests that exercise the production ``CoreAgent`` path
to confirm that signals fire from inside ``_execute_one`` (the real agent
loop), not just the standalone ``ToolExecutor.execute`` method introduced in
T9.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from breadmind.memory.episodic_store import EpisodicFilter
from breadmind.memory.event_types import SignalKind


@pytest.mark.asyncio
async def test_recall_runs_before_tool_call(tool_executor_factory):
    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()
    ex = tool_executor_factory(store=store, recorder=rec)

    await ex.execute(
        tool_name="aws_vpc_create",
        args={"region": "ap-northeast-2"},
        user_id="alice",
        session_id=None,
    )

    assert store.search.await_count >= 1
    f: EpisodicFilter = store.search.await_args.kwargs["filters"]
    assert f.tool_name == "aws_vpc_create"
    assert SignalKind.TOOL_EXECUTED in (f.kinds or [])


@pytest.mark.asyncio
async def test_recall_failure_does_not_block_execution(tool_executor_factory):
    store = AsyncMock()
    store.search.side_effect = RuntimeError("oh no")
    rec = AsyncMock()
    ex = tool_executor_factory(store=store, recorder=rec)

    out = await ex.execute(
        tool_name="echo",
        args={"x": "1"},
        user_id="alice",
        session_id=None,
    )

    assert out is not None  # tool still ran


@pytest.mark.asyncio
async def test_post_call_emits_signal(tool_executor_factory):
    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()
    ex = tool_executor_factory(store=store, recorder=rec)

    await ex.execute(
        tool_name="echo",
        args={"x": "1"},
        user_id="alice",
        session_id=None,
    )

    # SignalDetector.on_tool_finished always returns a SignalEvent for tool runs,
    # so recorder.record must be awaited exactly once (fire-and-forget task).
    # Allow the spawned task to run.
    import asyncio
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert rec.record.await_count == 1
    evt = rec.record.await_args.args[0]
    assert evt.kind in (SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED)


# ── T9.5: production CoreAgent path emits signals from _execute_one ───


def _drain_loop_helper():
    """Return a coroutine that yields to the event loop a few times so
    fire-and-forget tasks scheduled inside ``_execute_one`` get to run before
    we assert on the recorder mock."""
    import asyncio

    async def _drain():
        for _ in range(3):
            await asyncio.sleep(0)

    return _drain()


@pytest.mark.asyncio
async def test_production_path_emits_tool_executed_signal(make_agent):
    """The CoreAgent's normal handle_message path must fire a TOOL_EXECUTED
    signal when the LLM produces a tool call.

    This guards against the T9 regression where signals only fired from the
    standalone ``ToolExecutor.execute`` method but never from the production
    ``CoreAgent → process_tool_calls → _execute_one`` chain.
    """
    from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage

    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()

    agent = make_agent(recorder=rec, episodic_store=store)

    # First chat() call produces ONE tool call; second call (after the tool
    # result is appended) returns a final assistant turn with no tool calls
    # so the agent loop terminates cleanly.
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
    agent._provider.chat = AsyncMock(side_effect=[tool_response, final_response])

    result = await agent.handle_message(
        "run the tool please", user="frank", channel="general",
    )
    await _drain_loop_helper()

    # Final assistant text returned cleanly.
    assert result == "done"

    # The recorder must have been awaited for a TOOL_EXECUTED event from the
    # production _execute_one path.
    kinds = [c.args[0].kind for c in rec.record.await_args_list]
    assert SignalKind.TOOL_EXECUTED in kinds, (
        f"expected TOOL_EXECUTED signal from _execute_one; got kinds={kinds}"
    )

    # Pre-call recall must have executed too.
    assert store.search.await_count >= 1
    f: EpisodicFilter = store.search.await_args.kwargs["filters"]
    assert f.tool_name == "test_tool"
    assert SignalKind.TOOL_EXECUTED in (f.kinds or [])


@pytest.mark.asyncio
async def test_production_path_no_episodic_store_is_safe(make_agent):
    """If ``episodic_store`` is not wired but a recorder IS, the production
    path must still emit the post-call signal (recall is simply skipped)."""
    from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage

    rec = AsyncMock()
    agent = make_agent(recorder=rec, episodic_store=None)

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
    agent._provider.chat = AsyncMock(side_effect=[tool_response, final_response])

    result = await agent.handle_message("go", user="grace", channel="general")
    await _drain_loop_helper()

    assert result == "done"
    kinds = [c.args[0].kind for c in rec.record.await_args_list]
    assert SignalKind.TOOL_EXECUTED in kinds


@pytest.mark.asyncio
async def test_production_path_no_recorder_is_safe(make_agent):
    """No recorder + no store ⇒ tool still runs, no exception."""
    from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage

    agent = make_agent(recorder=None, episodic_store=None)

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
    agent._provider.chat = AsyncMock(side_effect=[tool_response, final_response])

    result = await agent.handle_message("go", user="hank", channel="general")
    assert result == "done"


@pytest.mark.asyncio
async def test_production_path_recall_failure_does_not_break_tool(make_agent):
    """If episodic_store.search raises, the tool must still execute and the
    final response must be returned cleanly."""
    from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage

    store = AsyncMock()
    store.search.side_effect = RuntimeError("recall blew up")
    rec = AsyncMock()

    agent = make_agent(recorder=rec, episodic_store=store)

    tool_response = LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="tc_1", name="test_tool", arguments={"input": "x"})],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="tool_use",
    )
    final_response = LLMResponse(
        content="done",
        tool_calls=[],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="end_turn",
    )
    agent._provider.chat = AsyncMock(side_effect=[tool_response, final_response])

    result = await agent.handle_message("go", user="ivy", channel="general")
    await _drain_loop_helper()

    assert result == "done"
    # Even though recall failed, the post-call signal must still fire.
    kinds = [c.args[0].kind for c in rec.record.await_args_list]
    assert SignalKind.TOOL_EXECUTED in kinds
