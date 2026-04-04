import pytest
from breadmind.core.v2_events import EventBus

@pytest.fixture
def bus():
    return EventBus()

def test_on_and_emit(bus):
    received = []
    bus.on("test.event", lambda data: received.append(data))
    bus.emit("test.event", {"key": "value"})
    assert len(received) == 1
    assert received[0]["key"] == "value"

def test_multiple_listeners(bus):
    results = []
    bus.on("multi", lambda d: results.append("a"))
    bus.on("multi", lambda d: results.append("b"))
    bus.emit("multi", {})
    assert results == ["a", "b"]

def test_no_listener_does_not_raise(bus):
    bus.emit("unknown.event", {})

def test_off_removes_listener(bus):
    results = []
    handler = lambda d: results.append(d)
    bus.on("removable", handler)
    bus.off("removable", handler)
    bus.emit("removable", "data")
    assert results == []

@pytest.mark.asyncio
async def test_async_emit(bus):
    results = []
    async def async_handler(data):
        results.append(data)
    bus.on("async.event", async_handler)
    await bus.async_emit("async.event", "hello")
    assert results == ["hello"]
