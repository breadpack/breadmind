import json
import uuid
from unittest.mock import AsyncMock

import pytest
from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
from breadmind.memory.event_types import SignalEvent, SignalKind


def _evt(kind=SignalKind.TOOL_FAILED, **kw):
    base = dict(
        kind=kind,
        user_id="alice",
        session_id=uuid.uuid4(),
        user_message=None,
        tool_name="aws_vpc_create",
        tool_args={"region": "ap-northeast-2"},
        tool_result_text="error: limit exceeded",
        prior_turn_summary=None,
    )
    base.update(kw)
    return SignalEvent(**base)


@pytest.mark.asyncio
async def test_records_with_llm_normalization():
    store = AsyncMock()
    llm = AsyncMock()
    llm.complete_json.return_value = {
        "summary": "VPC 생성이 한도 초과로 실패함.",
        "keywords": ["vpc", "limit", "fail"],
        "outcome": "failure",
        "should_record": True,
    }
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=True))
    await rec.record(_evt())
    assert store.write.await_count == 1
    note = store.write.await_args.args[0]
    assert note.outcome == "failure"
    assert "vpc" in note.keywords
    assert note.summary.startswith("VPC")


@pytest.mark.asyncio
async def test_should_record_false_skips_write():
    store = AsyncMock()
    llm = AsyncMock()
    llm.complete_json.return_value = {
        "summary": "trivial", "keywords": [],
        "outcome": "neutral", "should_record": False,
    }
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=True))
    await rec.record(_evt())
    assert store.write.await_count == 0


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_raw():
    store = AsyncMock()
    llm = AsyncMock()
    llm.complete_json.side_effect = TimeoutError()
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=True))
    await rec.record(_evt())
    assert store.write.await_count == 1
    note = store.write.await_args.args[0]
    assert note.summary  # non-empty raw header
    assert note.outcome == "failure"  # derived from kind


@pytest.mark.asyncio
async def test_normalize_off_writes_raw_directly():
    store = AsyncMock()
    llm = AsyncMock()
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=False))
    await rec.record(_evt())
    llm.complete_json.assert_not_called()
    assert store.write.await_count == 1


@pytest.mark.asyncio
async def test_recorder_does_not_raise_on_store_failure():
    store = AsyncMock(); store.write.side_effect = RuntimeError("db down")
    llm = AsyncMock()
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=False))
    # Must not raise — Recorder failures are isolated from the agent loop.
    await rec.record(_evt())
