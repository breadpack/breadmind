"""T10: ReflexionEngine emits a REFLEXION SignalEvent to EpisodicRecorder.

The hook is fire-and-forget (``asyncio.create_task``), so we await one event
loop tick before asserting on the recorder mock.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from breadmind.memory.event_types import SignalKind


@pytest.mark.asyncio
async def test_reflexion_emits_signal(reflexion_factory):
    rec = AsyncMock()
    refl = reflexion_factory(recorder=rec)

    await refl.record_lesson(
        "ap-northeast-2 has VPC quota issues; raise quota first.",
        user_id="alice",
        session_id=None,
    )

    # ``record_lesson`` schedules ``recorder.record(evt)`` via
    # ``asyncio.create_task``; yield once so the spawned coroutine runs.
    await asyncio.sleep(0)

    assert rec.record.await_count == 1
    assert rec.record.await_args.args[0].kind is SignalKind.REFLEXION


@pytest.mark.asyncio
async def test_reflexion_no_recorder_is_noop(reflexion_factory):
    """Without a recorder the engine must still persist the lesson but not crash."""
    refl = reflexion_factory(recorder=None)
    await refl.record_lesson("k8s rolling restart needs PDB review.", user_id="bob")
    # add_note on the (mocked) episodic memory was still invoked
    refl._episodic.add_note.assert_awaited_once()


@pytest.mark.asyncio
async def test_reflexion_signal_carries_user_and_text(reflexion_factory):
    rec = AsyncMock()
    refl = reflexion_factory(recorder=rec)
    await refl.record_lesson("lesson body", user_id="carol", session_id=None)
    await asyncio.sleep(0)

    evt = rec.record.await_args.args[0]
    assert evt.kind is SignalKind.REFLEXION
    assert evt.user_id == "carol"
    assert evt.user_message == "lesson body"
