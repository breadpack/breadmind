import asyncio
from uuid import uuid4

from breadmind.flow.events import FlowEvent, EventType, FlowActor
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore


async def test_publish_then_subscribe_receives(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    flow_id = uuid4()
    received: list[FlowEvent] = []

    async def listener():
        async for ev in bus.subscribe("sub-a", flow_id=flow_id):
            received.append(ev)
            if ev.event_type == EventType.FLOW_CREATED:
                return

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.05)

    await bus.publish(FlowEvent(
        flow_id=flow_id, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "T", "description": "", "user_id": "u", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))
    await asyncio.wait_for(task, timeout=1.0)
    assert len(received) == 1
    assert received[0].event_type == EventType.FLOW_CREATED
    await bus.stop()


async def test_subscribe_filters_by_flow_id(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    flow_a, flow_b = uuid4(), uuid4()
    received: list[FlowEvent] = []

    async def listener():
        async for ev in bus.subscribe("sub-b", flow_id=flow_a):
            received.append(ev)
            if len(received) >= 1:
                return

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.05)

    await bus.publish(FlowEvent(
        flow_id=flow_b, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "B", "description": "", "user_id": "u", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))
    await bus.publish(FlowEvent(
        flow_id=flow_a, seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={"title": "A", "description": "", "user_id": "u", "origin": "chat"},
        actor=FlowActor.AGENT,
    ))

    await asyncio.wait_for(task, timeout=1.0)
    assert len(received) == 1
    assert received[0].flow_id == flow_a
    await bus.stop()
