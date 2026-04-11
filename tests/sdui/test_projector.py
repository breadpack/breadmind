from uuid import uuid4

from breadmind.sdui.projector import UISpecProjector
from breadmind.flow.store import FlowEventStore
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import FlowEvent, EventType, FlowActor


def _find_by_type(component, type_name):
    found = []
    if component.type == type_name:
        found.append(component)
    for child in component.children:
        found.extend(_find_by_type(child, type_name))
    return found


def _all_types(component):
    types = {component.type}
    for child in component.children:
        types |= _all_types(child)
    return types


def _find_text_containing(component, needle):
    found = []
    if component.type in ("text", "heading") and needle in str(component.props.get("value", "")):
        found.append(component)
    for child in component.children:
        found.extend(_find_text_containing(child, needle))
    return found


async def test_chat_view_has_input_form(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        projector = UISpecProjector(db=test_db, bus=bus)
        spec = await projector.build_view("chat_view", user_id="alice")
        assert spec.root.type == "page"
        types = _all_types(spec.root)
        assert "form" in types
        assert "field" in types
        assert "button" in types
    finally:
        await bus.stop()


async def test_flow_list_view_renders_flows(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        projector = UISpecProjector(db=test_db, bus=bus)

        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "Build dashboard", "description": "D", "user_id": "alice", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))

        spec = await projector.build_view("flow_list_view", user_id="alice")
        assert spec.root.type == "page"
        titles = _find_text_containing(spec.root, "Build dashboard")
        assert titles, "expected flow title in list view"
    finally:
        await bus.stop()


async def test_flow_list_view_isolates_by_user(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        projector = UISpecProjector(db=test_db, bus=bus)

        flow_a = uuid4()
        flow_b = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_a, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "Alice's task", "description": "", "user_id": "alice", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_b, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "Bob's task", "description": "", "user_id": "bob", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))

        spec_alice = await projector.build_view("flow_list_view", user_id="alice")
        assert _find_text_containing(spec_alice.root, "Alice's task")
        assert not _find_text_containing(spec_alice.root, "Bob's task")
    finally:
        await bus.stop()


async def test_flow_detail_view_includes_dag_and_steps(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        projector = UISpecProjector(db=test_db, bus=bus)

        flow_id = uuid4()
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
            actor=FlowActor.AGENT,
        ))
        await bus.publish(FlowEvent(
            flow_id=flow_id, seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": [
                {"id": "a", "title": "A", "tool": "t", "args": {}, "depends_on": []},
                {"id": "b", "title": "B", "tool": "t", "args": {}, "depends_on": ["a"]},
            ]},
            actor=FlowActor.AGENT,
        ))
        spec = await projector.build_view("flow_detail_view", flow_id=str(flow_id))
        types = _all_types(spec.root)
        assert "dag_view" in types
        assert "step_card" in types
    finally:
        await bus.stop()


async def test_flow_detail_view_missing_flow(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        projector = UISpecProjector(db=test_db, bus=bus)
        fake_id = str(uuid4())
        spec = await projector.build_view("flow_detail_view", flow_id=fake_id)
        # Should render some kind of "not found" page, not crash
        assert spec.root.type == "page"
    finally:
        await bus.stop()
