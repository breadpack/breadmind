"""Tests for the Durable Task Flow event store."""
from __future__ import annotations

from uuid import uuid4

from breadmind.flow.events import EventType, FlowActor, FlowEvent
from breadmind.flow.store import FlowEventStore


async def test_append_assigns_sequence(test_db):
    store = FlowEventStore(test_db)
    flow_id = uuid4()

    e1 = await store.append(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "Test", "description": "", "user_id": "u1", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))
    assert e1.seq == 1

    e2 = await store.append(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.DAG_PROPOSED,
        payload={"steps": []},
        actor=FlowActor.AGENT,
    ))
    assert e2.seq == 2


async def test_append_creates_flow_projection(test_db):
    store = FlowEventStore(test_db)
    flow_id = uuid4()
    await store.append(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "Hello", "description": "World", "user_id": "alice", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))
    async with test_db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM flows WHERE id = $1", flow_id)
    assert row is not None
    assert row["title"] == "Hello"
    assert row["user_id"] == "alice"
    assert row["status"] == "pending"


async def test_replay_returns_events_in_order(test_db):
    store = FlowEventStore(test_db)
    flow_id = uuid4()
    # Create the flow first so step events can be applied (they call _touch_flow).
    await store.append(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))
    for i in range(3):
        await store.append(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.STEP_STARTED,
            payload={"step_id": f"s{i}", "started_at": "2026-04-10T00:00:00Z"},
            actor=FlowActor.WORKER,
        ))
    events = await store.replay(flow_id)
    # Should have 1 (flow_created) + 3 (step_started) = 4 events
    assert len(events) == 4
    assert [e.seq for e in events] == [1, 2, 3, 4]


async def test_dag_proposed_inserts_steps(test_db):
    store = FlowEventStore(test_db)
    flow_id = uuid4()
    await store.append(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))
    await store.append(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.DAG_PROPOSED,
        payload={"steps": [
            {"id": "s1", "title": "First", "tool": "shell_exec", "args": {}, "depends_on": []},
            {"id": "s2", "title": "Second", "tool": "shell_exec", "args": {}, "depends_on": ["s1"]},
        ]},
        actor=FlowActor.AGENT,
    ))
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT step_id, status FROM flow_steps WHERE flow_id = $1 ORDER BY step_id",
            flow_id,
        )
    assert [(r["step_id"], r["status"]) for r in rows] == [("s1", "pending"), ("s2", "pending")]
