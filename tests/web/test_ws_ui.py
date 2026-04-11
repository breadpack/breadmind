"""Tests for the /ws/ui WebSocket endpoint (Durable Task Flow — Task 14).

These tests drive ``handle_ws_ui`` directly with a fake ``WebSocket`` so we
do not need a running ASGI server or auth fixtures. The fake supports the
subset of the ``WebSocket`` interface that the handler uses:

* ``app.state`` / ``app.state.app_state`` — for locating the projector/bus.
* ``query_params`` / ``cookies`` — for the auth fallback.
* ``accept`` / ``receive_text`` / ``send_text`` / ``close``.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.projector import UISpecProjector
from breadmind.web.routes.ui import handle_ws_ui


class _FakeWebSocket:
    def __init__(self, app, incoming: list[str] | None = None, *, auto_disconnect: bool = True):
        self.app = app
        self._incoming: asyncio.Queue = asyncio.Queue()
        for item in (incoming or []):
            self._incoming.put_nowait(item)
        if auto_disconnect:
            self._incoming.put_nowait(None)
        self.sent: list[str] = []
        self.accepted = False
        self.closed: tuple[int, str] | None = None
        self.query_params: dict[str, str] = {"user": "alice"}
        self.cookies: dict[str, str] = {}

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if item is None:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)
        return item

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)

    def feed(self, msg: str | None) -> None:
        self._incoming.put_nowait(msg)

    def disconnect(self) -> None:
        self._incoming.put_nowait(None)


def _make_fake_app(projector: UISpecProjector, flow_bus: FlowEventBus):
    """Build a stand-in for ``WebSocket.app`` with the minimum surface area."""
    state = SimpleNamespace(
        uispec_projector=projector,
        flow_event_bus=flow_bus,
        app_state=SimpleNamespace(_db=None, _auth=None),
    )
    return SimpleNamespace(state=state)


@pytest.fixture
async def projector_and_bus(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        yield UISpecProjector(db=test_db, bus=bus), bus
    finally:
        await bus.stop()


async def test_ws_ui_view_request_returns_spec_full(projector_and_bus):
    projector, bus = projector_and_bus
    app = _make_fake_app(projector, bus)

    ws = _FakeWebSocket(
        app,
        incoming=[json.dumps({
            "type": "view_request",
            "view_key": "chat_view",
            "params": {},
        })],
    )

    await handle_ws_ui(ws)

    assert ws.accepted, "handler must accept the connection"
    assert ws.sent, "handler must respond to view_request"
    msg = json.loads(ws.sent[0])
    assert msg["type"] == "spec_full"
    assert msg["view_key"] == "chat_view"
    assert msg["spec"]["root"]["type"] == "page"


async def test_ws_ui_action_view_request_switches_view(projector_and_bus):
    projector, bus = projector_and_bus
    app = _make_fake_app(projector, bus)

    ws = _FakeWebSocket(
        app,
        incoming=[
            json.dumps({"type": "view_request", "view_key": "chat_view"}),
            json.dumps({
                "type": "action",
                "action": {"kind": "view_request", "view_key": "flow_list_view"},
            }),
        ],
    )

    await handle_ws_ui(ws)

    types = [json.loads(m)["view_key"] for m in ws.sent if json.loads(m)["type"] == "spec_full"]
    assert types == ["chat_view", "flow_list_view"]


async def test_ws_ui_flow_event_triggers_patch(projector_and_bus):
    projector, bus = projector_and_bus
    app = _make_fake_app(projector, bus)

    ws = _FakeWebSocket(
        app,
        incoming=[json.dumps({"type": "view_request", "view_key": "flow_list_view"})],
        auto_disconnect=False,
    )

    async def drive() -> None:
        # Run the handler until it disconnects after consuming scripted messages.
        await handle_ws_ui(ws)

    handler_task = asyncio.create_task(drive())

    # Give the handler a chance to reach the receive loop and process the
    # initial view_request before we publish the flow event.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if any(json.loads(m).get("type") == "spec_full" for m in ws.sent):
            break

    await bus.publish(FlowEvent(
        flow_id=uuid4(),
        seq=0,
        event_type=EventType.FLOW_CREATED,
        payload={
            "title": "Patch test",
            "description": "",
            "user_id": "alice",
            "origin": "chat",
        },
        actor=FlowActor.AGENT,
    ))

    # Give the subscription loop time to run refresh_current + send_text.
    for _ in range(50):
        await asyncio.sleep(0.02)
        if any(json.loads(m).get("type") == "spec_patch" for m in ws.sent):
            break

    # Unblock the handler's receive loop so it disconnects cleanly.
    ws.disconnect()
    try:
        await asyncio.wait_for(handler_task, timeout=2.0)
    except asyncio.TimeoutError:
        handler_task.cancel()
        raise

    patches = [json.loads(m) for m in ws.sent if json.loads(m).get("type") == "spec_patch"]
    assert patches, "expected a spec_patch after FLOW_CREATED for the current user"
    assert patches[0]["view_key"] == "flow_list_view"
    assert isinstance(patches[0]["patch"], list)
