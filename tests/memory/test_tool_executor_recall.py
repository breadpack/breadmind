"""T9: ToolExecutor pre-call recall + post-call signal."""
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
