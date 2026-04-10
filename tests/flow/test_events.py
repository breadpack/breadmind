from uuid import uuid4
from datetime import datetime, timezone

from breadmind.flow.events import FlowEvent, EventType, FlowActor


def test_flow_event_roundtrip():
    flow_id = uuid4()
    event = FlowEvent(
        flow_id=flow_id,
        seq=1,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "T", "description": "D", "user_id": "u1", "origin": "chat"},
        actor=FlowActor.AGENT,
        created_at=datetime.now(timezone.utc),
    )
    d = event.to_dict()
    assert d["flow_id"] == str(flow_id)
    assert d["event_type"] == "flow_created"
    restored = FlowEvent.from_dict(d)
    assert restored.flow_id == flow_id
    assert restored.event_type == EventType.FLOW_CREATED


def test_event_type_values():
    assert EventType.STEP_STARTED.value == "step_started"
    assert EventType.STEP_COMPLETED.value == "step_completed"
    assert EventType.DAG_PROPOSED.value == "dag_proposed"


def test_flow_actor_values():
    assert FlowActor.AGENT.value == "agent"
    assert FlowActor.WORKER.value == "worker"
    assert FlowActor.USER.value == "user"
