import pytest

from breadmind.core.events import EventBus
from breadmind.hooks import HookDecision, HookEvent, HookPayload
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


async def test_safety_guard_hook_fires_on_deny(fresh_global_bus):
    """When SafetyGuard denies, SAFETY_GUARD_TRIGGERED is dispatched."""
    from breadmind.core.agent import CoreAgent
    from breadmind.core.safety import SafetyGuard, SafetyResult

    seen: list[dict] = []
    fresh_global_bus.register_hook(
        HookEvent.SAFETY_GUARD_TRIGGERED,
        PythonHook(
            name="spy",
            event=HookEvent.SAFETY_GUARD_TRIGGERED,
            handler=lambda p: (seen.append(dict(p.data)), HookDecision.proceed())[1],
        ),
    )

    # Build a bare agent + blacklisting SafetyGuard
    agent = CoreAgent.__new__(CoreAgent)
    agent._safety = SafetyGuard(blacklist={"shell": ["shell_exec"]})
    # Exercise the new _emit_safety_triggered helper (added by this task)
    result = await agent._emit_safety_triggered(
        action="shell_exec", params={"cmd": "ls"},
        user="u1", channel="c1",
        original=SafetyResult.DENY,
    )
    assert result == SafetyResult.DENY
    assert seen and seen[0]["action"] == "shell_exec"
    assert seen[0]["decision"] == "DENIED"


async def test_safety_guard_hook_can_override_to_allow(fresh_global_bus):
    from breadmind.core.agent import CoreAgent
    from breadmind.core.safety import SafetyResult

    fresh_global_bus.register_hook(
        HookEvent.SAFETY_GUARD_TRIGGERED,
        PythonHook(
            name="allow",
            event=HookEvent.SAFETY_GUARD_TRIGGERED,
            handler=lambda p: HookDecision.modify(decision="ALLOWED"),
        ),
    )

    agent = CoreAgent.__new__(CoreAgent)
    result = await agent._emit_safety_triggered(
        action="shell_exec", params={"cmd": "ls"},
        user="u1", channel="c1",
        original=SafetyResult.DENY,
    )
    assert result == SafetyResult.ALLOW


async def test_safety_guard_hook_block_forces_deny(fresh_global_bus):
    from breadmind.core.agent import CoreAgent
    from breadmind.core.safety import SafetyResult

    fresh_global_bus.register_hook(
        HookEvent.SAFETY_GUARD_TRIGGERED,
        PythonHook(
            name="block",
            event=HookEvent.SAFETY_GUARD_TRIGGERED,
            handler=lambda p: HookDecision.block("policy"),
        ),
    )

    agent = CoreAgent.__new__(CoreAgent)
    result = await agent._emit_safety_triggered(
        action="shell_exec", params={},
        user="u1", channel="c1",
        original=SafetyResult.REQUIRE_APPROVAL,
    )
    assert result == SafetyResult.DENY


async def test_plugin_loaded_event_fires(fresh_global_bus):
    """Directly exercising the emit helper — no real plugin needed."""
    from breadmind.core.events import get_event_bus
    from breadmind.hooks import HookEvent, HookPayload

    seen = []
    fresh_global_bus.register_hook(
        HookEvent.PLUGIN_LOADED,
        PythonHook(
            name="spy",
            event=HookEvent.PLUGIN_LOADED,
            handler=lambda p: (seen.append(dict(p.data)), HookDecision.proceed())[1],
        ),
    )
    await get_event_bus().run_hook_chain(
        HookEvent.PLUGIN_LOADED,
        HookPayload(
            event=HookEvent.PLUGIN_LOADED,
            data={"plugin_name": "demo", "version": "0.1.0", "path": "/tmp/demo"},
        ),
    )
    assert seen and seen[0]["plugin_name"] == "demo"


async def test_plugin_unloaded_event_fires(fresh_global_bus):
    from breadmind.core.events import get_event_bus
    from breadmind.hooks import HookEvent, HookPayload

    seen = []
    fresh_global_bus.register_hook(
        HookEvent.PLUGIN_UNLOADED,
        PythonHook(
            name="spy",
            event=HookEvent.PLUGIN_UNLOADED,
            handler=lambda p: (seen.append(dict(p.data)), HookDecision.proceed())[1],
        ),
    )
    await get_event_bus().run_hook_chain(
        HookEvent.PLUGIN_UNLOADED,
        HookPayload(
            event=HookEvent.PLUGIN_UNLOADED, data={"plugin_name": "demo"},
        ),
    )
    assert seen and seen[0]["plugin_name"] == "demo"


async def test_pre_compact_block_skips_compaction(fresh_global_bus):
    from breadmind.memory import compressor
    from breadmind.llm.base import LLMMessage

    fresh_global_bus.register_hook(
        HookEvent.PRE_COMPACT,
        PythonHook(
            name="skip",
            event=HookEvent.PRE_COMPACT,
            handler=lambda p: HookDecision.block("frozen"),
        ),
    )

    # 15 messages with keep_recent=10 would normally trigger compaction;
    # block must return the original unchanged.
    original = [LLMMessage(role="user", content=f"m{i}") for i in range(15)]

    class _BoomProvider:
        async def chat(self, *a, **kw):
            raise AssertionError("provider should not be called when blocked")

    result = await compressor.compress_history(
        list(original), _BoomProvider(), keep_recent=10,
    )
    assert len(result) == len(original)


async def test_pre_compact_hook_is_called(fresh_global_bus):
    from breadmind.memory import compressor
    from breadmind.llm.base import LLMMessage

    seen = []
    fresh_global_bus.register_hook(
        HookEvent.PRE_COMPACT,
        PythonHook(
            name="spy",
            event=HookEvent.PRE_COMPACT,
            handler=lambda p: (seen.append(dict(p.data)), HookDecision.proceed())[1],
        ),
    )

    # len(messages) <= keep_recent triggers early-return after the hook fires,
    # so no provider call is needed.
    await compressor.compress_history(
        [LLMMessage(role="user", content="a")],
        provider=None,
        keep_recent=10,
    )
    assert len(seen) == 1
    assert "messages_count" in seen[0]
    assert "messages" in seen[0]


async def test_pre_compact_modify_replaces_messages(fresh_global_bus):
    from breadmind.memory import compressor
    from breadmind.llm.base import LLMMessage

    replacement = [LLMMessage(role="system", content="SUMMARY")]
    fresh_global_bus.register_hook(
        HookEvent.PRE_COMPACT,
        PythonHook(
            name="replace",
            event=HookEvent.PRE_COMPACT,
            handler=lambda p: HookDecision.modify(messages=list(replacement)),
        ),
    )

    # Originally 15 messages; modify replaces with 1 message. The replacement
    # has len 1 <= keep_recent=10, so compress_history early-returns the
    # replacement unchanged — proving the patch was honored.
    original = [LLMMessage(role="user", content=f"m{i}") for i in range(15)]
    result = await compressor.compress_history(
        list(original), provider=None, keep_recent=10,
    )
    assert len(result) == 1
    assert result[0].content == "SUMMARY"


async def test_memory_written_event_fires_from_chain():
    """Observational event: just verify dispatch via the chain is reachable."""
    from breadmind.core.events import EventBus
    from breadmind.hooks import HookEvent, HookPayload

    # Use a scoped bus so we don't depend on monkeypatch quirks
    bus = EventBus()
    seen = []
    bus.register_hook(
        HookEvent.MEMORY_WRITTEN,
        PythonHook(
            name="spy",
            event=HookEvent.MEMORY_WRITTEN,
            handler=lambda p: (seen.append(dict(p.data)), HookDecision.proceed())[1],
        ),
    )
    await bus.run_hook_chain(
        HookEvent.MEMORY_WRITTEN,
        HookPayload(
            event=HookEvent.MEMORY_WRITTEN,
            data={"layer": "semantic", "kind": "entity", "item_id": "e1"},
        ),
    )
    assert seen and seen[0]["layer"] == "semantic"
    assert seen[0]["kind"] == "entity"
