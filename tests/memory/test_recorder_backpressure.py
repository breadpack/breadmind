import asyncio
from unittest.mock import AsyncMock

import pytest

from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
from breadmind.memory.event_types import SignalEvent, SignalKind


def _evt(i: int) -> SignalEvent:
    return SignalEvent(
        kind=SignalKind.TOOL_EXECUTED,
        user_id="alice",
        session_id=None,
        user_message=None,
        tool_name=f"t{i}",
        tool_args={"i": i},
        tool_result_text="ok",
        prior_turn_summary=None,
    )


@pytest.mark.asyncio
async def test_queue_threshold_falls_back_to_raw():
    store = AsyncMock()
    slow_llm = AsyncMock()

    async def slow_complete_json(_):
        await asyncio.sleep(0.5)
        return {
            "summary": "s",
            "keywords": [],
            "outcome": "success",
            "should_record": True,
        }

    slow_llm.complete_json.side_effect = slow_complete_json

    rec = EpisodicRecorder(
        store=store,
        llm=slow_llm,
        config=RecorderConfig(
            normalize=True, semaphore_size=1, queue_max=2, timeout_sec=2.0
        ),
    )
    # Fire 6 in flight; queue_max=2 means most should bypass LLM (raw fallback path).
    await asyncio.gather(*(rec.record(_evt(i)) for i in range(6)))
    # All 6 must have been written exactly once.
    assert store.write.await_count == 6
    # At least one should be the raw-fallback path (LLM not called).
    assert slow_llm.complete_json.await_count < 6
