"""Smoke test: CoreAgent exposes a hook-emitting helper that dispatches
through the shared EventBus chain. We don't drive a full agent run —
we instantiate a bare CoreAgent via __new__ and call _emit_hook directly,
asserting the event bus records the event.
"""
import pytest

from breadmind.core.events import EventBus
from breadmind.hooks import HookEvent


class _RecordingBus(EventBus):
    def __init__(self):
        super().__init__()
        self.recorded: list[tuple[str, dict]] = []

    async def run_hook_chain(self, event, payload):
        key = event.value if hasattr(event, "value") else str(event)
        self.recorded.append((key, dict(payload.data)))
        return await super().run_hook_chain(event, payload)


@pytest.fixture
def recording_bus(monkeypatch):
    bus = _RecordingBus()
    import breadmind.core.events as ev
    monkeypatch.setattr(ev, "_bus", bus)
    return bus


async def test_core_agent_emit_hook_dispatches_through_bus(recording_bus):
    from breadmind.core.agent import CoreAgent

    agent = CoreAgent.__new__(CoreAgent)
    await agent._emit_hook(HookEvent.SESSION_START, {"session_id": "s1"})
    await agent._emit_hook(HookEvent.USER_PROMPT_SUBMIT, {"prompt": "hi"})
    await agent._emit_hook(HookEvent.STOP, {"session_id": "s1"})

    events = [name for name, _ in recording_bus.recorded]
    assert "session_start" in events
    assert "user_prompt_submit" in events
    assert "stop" in events
