import pytest

from breadmind.core.events import EventBus
from breadmind.hooks import HookDecision, HookEvent
from breadmind.hooks.handler import PythonHook


@pytest.fixture
def fresh_global_bus(monkeypatch):
    import breadmind.core.events as ev
    monkeypatch.setattr(ev, "_bus", EventBus())
    return ev._bus


async def test_messenger_received_helper_dispatches(fresh_global_bus):
    seen = []
    fresh_global_bus.register_hook(
        HookEvent.MESSENGER_RECEIVED,
        PythonHook(
            name="spy",
            event=HookEvent.MESSENGER_RECEIVED,
            handler=lambda p: (seen.append(dict(p.data)), HookDecision.proceed())[1],
        ),
    )
    from breadmind.messenger.router import emit_messenger_received, IncomingMessage
    msg = IncomingMessage(
        text="hi", user_id="u1", channel_id="c1", platform="slack",
    )
    decision = await emit_messenger_received(msg)
    assert decision.kind.value == "proceed"
    assert len(seen) == 1
    assert seen[0]["text"] == "hi"
    assert seen[0]["platform"] == "slack"


async def test_messenger_received_can_block(fresh_global_bus):
    fresh_global_bus.register_hook(
        HookEvent.MESSENGER_RECEIVED,
        PythonHook(
            name="deny",
            event=HookEvent.MESSENGER_RECEIVED,
            handler=lambda p: HookDecision.block("muted"),
        ),
    )
    from breadmind.messenger.router import emit_messenger_received, IncomingMessage
    msg = IncomingMessage(text="x", user_id="u", channel_id="c", platform="slack")
    decision = await emit_messenger_received(msg)
    assert decision.kind.value == "block"
    assert decision.reason == "muted"


async def test_gateway_wrapper_drops_blocked_message(fresh_global_bus):
    fresh_global_bus.register_hook(
        HookEvent.MESSENGER_RECEIVED,
        PythonHook(
            name="deny",
            event=HookEvent.MESSENGER_RECEIVED,
            handler=lambda p: HookDecision.block("no"),
        ),
    )

    from breadmind.messenger.router import MessengerGateway, IncomingMessage

    # Build a minimal concrete subclass only for the wrapper check.
    received = []

    async def client_callback(incoming):
        received.append(incoming)

    class _StubGateway(MessengerGateway):
        async def start(self): ...
        async def stop(self): ...
        async def send(self, channel_id: str, text: str): ...

    gw = _StubGateway("slack", client_callback)

    # Call the gateway's wrapped callback directly
    msg = IncomingMessage(text="x", user_id="u", channel_id="c", platform="slack")
    await gw._on_message(msg)
    assert received == []  # blocked
