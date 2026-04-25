"""Integration scenarios A / B / C / pin for the episodic loop.

These tests exercise the full recorder + store pipeline against a real
PostgreSQL via the shared ``test_db`` fixture (see ``tests/conftest.py``).

The shared fixture is non-isolated across tests (carry-over #3 in the
Phase 1 plan), so each scenario uses a unique ``user_id`` to avoid
cross-test contamination.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
from breadmind.memory.episodic_store import EpisodicFilter, PostgresEpisodicStore
from breadmind.memory.event_types import SignalKind, stable_hash
from breadmind.memory.signals import SignalDetector, TurnSnapshot


def _uid(tag: str) -> str:
    """Unique per-test user_id to keep the non-isolated fixture clean."""
    return f"alice-{tag}-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_scenario_A_dialog_continuity(test_db):
    """Tool runs in session 1; in session 2 the recall pulls the prior fact."""
    user_id = _uid("A")
    store = PostgresEpisodicStore(test_db)
    llm = AsyncMock()
    llm.complete_json.return_value = {
        "summary": "VPC ap-northeast-2 was created.",
        "keywords": ["vpc", "ap-northeast-2"],
        "outcome": "success",
        "should_record": True,
    }
    rec = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig(normalize=True))
    sig = SignalDetector()

    sid1 = uuid.uuid4()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=sid1,
        user_message="VPC를 ap-northeast-2에 만들어줘",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    evt = sig.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args={"region": "ap-northeast-2"},
        ok=True,
        result_text="vpc-001 created",
    )
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query="어제 그 VPC 어떻게 됐지?",
        filters=EpisodicFilter(),
        limit=5,
    )
    assert any(
        "ap-northeast-2" in (n.summary + " ".join(n.keywords)) for n in notes
    )


@pytest.mark.asyncio
async def test_scenario_B_task_recall_same_args(test_db):
    """Same tool with same args -> digest match should boost recall to top."""
    user_id = _uid("B")
    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=uuid.uuid4(),
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
    )

    args = {"region": "ap-northeast-2", "name": "vpc-a"}
    evt = sig.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args=args,
        ok=True,
        result_text="vpc-001 created",
    )
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(
            tool_name="aws_vpc_create",
            tool_args_digest=stable_hash(args),
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
        ),
        limit=3,
    )
    assert notes and notes[0].tool_args_digest == stable_hash(args)


@pytest.mark.asyncio
async def test_scenario_C_failure_learning(test_db):
    """A failure on tool X should surface first when X is invoked again."""
    user_id = _uid("C")
    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=None,
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    e1 = sig.on_tool_finished(
        snap, tool_name="t", tool_args={"a": 1}, ok=True, result_text="ok"
    )
    await rec.record(e1)
    e2 = sig.on_tool_finished(
        snap, tool_name="t", tool_args={"a": 2}, ok=False, result_text="boom"
    )
    await rec.record(e2)

    notes = await store.search(
        user_id=user_id,
        query=None,
        filters=EpisodicFilter(
            tool_name="t",
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
        ),
        limit=3,
    )
    assert notes[0].outcome == "failure"


@pytest.mark.asyncio
async def test_scenario_pin(test_db):
    """An explicit pin should be persisted and surfaced first on later recall."""
    user_id = _uid("pin")
    store = PostgresEpisodicStore(test_db)
    rec = EpisodicRecorder(
        store=store,
        llm=AsyncMock(),
        config=RecorderConfig(normalize=False),
    )
    sig = SignalDetector()
    snap = TurnSnapshot(
        user_id=user_id,
        session_id=None,
        user_message="기억해줘: API key는 vault X에 있다",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    evt = sig.on_user_message(snap)
    assert evt and evt.kind is SignalKind.EXPLICIT_PIN
    await rec.record(evt)

    notes = await store.search(
        user_id=user_id,
        query="API key 어디에 있지?",
        filters=EpisodicFilter(),
        limit=5,
    )
    assert any(n.pinned for n in notes)
