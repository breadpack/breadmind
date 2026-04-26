"""T7: org_id plumbing through CoreAgent.handle_message + ToolExecutionContext.

These tests exercise the per-turn org_id contract:

  * ``handle_message(..., org_id=UUID(...))`` is the sole authority for the
    turn's org_id. It is plumbed into the user-signal TurnSnapshot, into the
    ToolExecutionContext, and through ``_do_recall`` → ``EpisodicFilter``.
  * When the caller passes ``org_id=None``, ``_resolve_org_id`` consults
    ``BREADMIND_DEFAULT_ORG_ID`` as the env fallback.
  * No ``default_org_id`` is added to ``CoreAgent.__init__``; the contract is
    ctx-only.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from breadmind.core.tool_executor import ToolExecutionContext, ToolExecutor
from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage
from breadmind.memory.episodic_store import EpisodicFilter
from breadmind.memory.event_types import SignalKind


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


_ORG_EXPLICIT = uuid.UUID("00000000-0000-0000-0000-000000000001")
_ORG_ENV = uuid.UUID("00000000-0000-0000-0000-0000000000ff")


async def _drain_pending_tasks() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


def _make_chat_pair(*, with_tool: bool):
    """Return [tool_response, final_response] for AsyncMock side_effect.

    When ``with_tool=True`` the first response carries a ToolCall so the
    agent enters ``process_tool_calls`` (and thus _do_recall + _emit_tool_signal).
    """
    final_response = LLMResponse(
        content="done",
        tool_calls=[],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="end_turn",
    )
    if not with_tool:
        return [final_response]
    tool_response = LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="tc_1", name="test_tool", arguments={"input": "x"})],
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        stop_reason="tool_use",
    )
    return [tool_response, final_response]


# ──────────────────────────────────────────────────────────────────────────
# 1. handle_message(org_id=...) → user-signal TurnSnapshot.org_id
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_message_propagates_org_id_to_user_signal(make_agent):
    """An explicit org_id passed to handle_message must surface as
    SignalEvent.org_id on the user-signal recorder call."""
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    # Use an EXPLICIT_PIN message so on_user_message returns a SignalEvent.
    await agent.handle_message(
        "기억해줘: org A's API key lives in vault Y",
        user="alice",
        channel="general",
        org_id=_ORG_EXPLICIT,
    )
    await _drain_pending_tasks()

    assert rec.record.await_count >= 1
    evt = rec.record.await_args_list[0].args[0]
    assert evt.kind is SignalKind.EXPLICIT_PIN
    assert evt.org_id == _ORG_EXPLICIT


@pytest.mark.asyncio
async def test_handle_message_org_id_none_uses_env_fallback(
    make_agent, monkeypatch
):
    """When the caller passes org_id=None, _resolve_org_id must consult
    BREADMIND_DEFAULT_ORG_ID and the resolved value must propagate into the
    emitted SignalEvent."""
    monkeypatch.setenv("BREADMIND_DEFAULT_ORG_ID", str(_ORG_ENV))
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    await agent.handle_message(
        "기억해줘: env fallback test",
        user="bob",
        channel="general",
        org_id=None,
    )
    await _drain_pending_tasks()

    assert rec.record.await_count >= 1
    evt = rec.record.await_args_list[0].args[0]
    assert evt.kind is SignalKind.EXPLICIT_PIN
    assert evt.org_id == _ORG_ENV


@pytest.mark.asyncio
async def test_handle_message_explicit_org_id_overrides_env(
    make_agent, monkeypatch
):
    """Explicit org_id wins over BREADMIND_DEFAULT_ORG_ID env."""
    monkeypatch.setenv("BREADMIND_DEFAULT_ORG_ID", str(_ORG_ENV))
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    await agent.handle_message(
        "기억해줘: explicit wins",
        user="carol",
        channel="general",
        org_id=_ORG_EXPLICIT,
    )
    await _drain_pending_tasks()

    evt = rec.record.await_args_list[0].args[0]
    assert evt.org_id == _ORG_EXPLICIT


# ──────────────────────────────────────────────────────────────────────────
# 2. ToolExecutionContext.org_id field exists and is plumbed
# ──────────────────────────────────────────────────────────────────────────


def test_tool_execution_context_carries_org_id():
    ctx = ToolExecutionContext(
        user="u",
        channel="c",
        session_id="u:c",
        working_memory=None,
        audit_logger=None,
        tool_gap_detector=None,
        context_builder=None,
        org_id=_ORG_EXPLICIT,
    )
    assert ctx.org_id == _ORG_EXPLICIT


def test_tool_execution_context_org_id_defaults_none():
    ctx = ToolExecutionContext(
        user="u",
        channel="c",
        session_id="u:c",
        working_memory=None,
        audit_logger=None,
        tool_gap_detector=None,
        context_builder=None,
    )
    assert ctx.org_id is None


# ──────────────────────────────────────────────────────────────────────────
# 3. _do_recall passes ctx.org_id into EpisodicFilter
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_do_recall_forwards_org_id_to_episodic_filter(tool_executor_factory):
    """When ``_do_recall`` is invoked with an org_id kwarg it must construct
    EpisodicFilter with that org_id."""
    store = AsyncMock()
    store.search.return_value = []
    ex: ToolExecutor = tool_executor_factory(store=store, recorder=AsyncMock())

    await ex._do_recall(
        tool_name="echo",
        args={"x": "1"},
        user_id="alice",
        org_id=_ORG_EXPLICIT,
    )

    assert store.search.await_count == 1
    flt: EpisodicFilter = store.search.await_args.kwargs["filters"]
    assert flt.org_id == _ORG_EXPLICIT


@pytest.mark.asyncio
async def test_do_recall_org_id_none_yields_filter_with_none(tool_executor_factory):
    """Default behaviour: no org_id → EpisodicFilter.org_id is None."""
    store = AsyncMock()
    store.search.return_value = []
    ex: ToolExecutor = tool_executor_factory(store=store, recorder=AsyncMock())

    await ex._do_recall(tool_name="echo", args={"x": "1"}, user_id="alice")

    assert store.search.await_count == 1
    flt: EpisodicFilter = store.search.await_args.kwargs["filters"]
    assert flt.org_id is None


# ──────────────────────────────────────────────────────────────────────────
# 4. End-to-end: handle_message(org_id=...) → EpisodicFilter.org_id
#    when the agent loop fires a tool call.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_message_org_id_reaches_episodic_filter_via_execute_one(
    make_agent,
):
    """When handle_message runs a tool, the recall EpisodicFilter must carry
    the same org_id that the caller supplied."""
    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()
    agent = make_agent(recorder=rec, episodic_store=store)
    agent._provider.chat = AsyncMock(side_effect=_make_chat_pair(with_tool=True))

    await agent.handle_message(
        "run the tool", user="dave", channel="general", org_id=_ORG_EXPLICIT,
    )
    await _drain_pending_tasks()

    assert store.search.await_count >= 1
    flt: EpisodicFilter = store.search.await_args.kwargs["filters"]
    assert flt.org_id == _ORG_EXPLICIT


@pytest.mark.asyncio
async def test_handle_message_org_id_reaches_tool_signal_event(make_agent):
    """The post-tool-call SignalEvent emitted from _execute_one must carry
    the org_id supplied to handle_message."""
    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()
    agent = make_agent(recorder=rec, episodic_store=store)
    agent._provider.chat = AsyncMock(side_effect=_make_chat_pair(with_tool=True))

    await agent.handle_message(
        "run the tool", user="erin", channel="general", org_id=_ORG_EXPLICIT,
    )
    await _drain_pending_tasks()

    # Find the TOOL_EXECUTED signal in the recorder calls and check its org_id.
    tool_evts = [
        c.args[0]
        for c in rec.record.await_args_list
        if c.args and c.args[0].kind is SignalKind.TOOL_EXECUTED
    ]
    assert tool_evts, "expected at least one TOOL_EXECUTED signal"
    assert all(e.org_id == _ORG_EXPLICIT for e in tool_evts)


# ──────────────────────────────────────────────────────────────────────────
# 5. ToolExecutor.execute() standalone path keeps org_id=None (no ctx)
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_standalone_execute_uses_no_org_id(tool_executor_factory):
    """The standalone ToolExecutor.execute() helper has no ctx, so the
    EpisodicFilter it constructs must have org_id=None."""
    store = AsyncMock()
    store.search.return_value = []
    rec = AsyncMock()
    ex: ToolExecutor = tool_executor_factory(store=store, recorder=rec)

    await ex.execute(tool_name="echo", args={"x": "1"}, user_id="alice")

    flt: EpisodicFilter = store.search.await_args.kwargs["filters"]
    assert flt.org_id is None


# ──────────────────────────────────────────────────────────────────────────
# 6. Backward-compat: positional call without org_id keyword still works.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_message_without_org_id_kwarg_still_works(make_agent):
    """Existing callers that don't pass org_id must continue to work."""
    rec = AsyncMock()
    agent = make_agent(recorder=rec)

    result = await agent.handle_message(
        "안녕", user="frank", channel="general",
    )
    assert result == "ok"


# ──────────────────────────────────────────────────────────────────────────
# 7. Smoke: agent constructor signature unchanged (no default_org_id).
# ──────────────────────────────────────────────────────────────────────────


def test_core_agent_init_does_not_accept_default_org_id():
    """Per T7 contract: org_id is ctx-only; CoreAgent.__init__ must NOT
    accept a default_org_id parameter."""
    import inspect

    from breadmind.core.agent import CoreAgent

    sig = inspect.signature(CoreAgent.__init__)
    assert "default_org_id" not in sig.parameters
