"""Tests for the 15 extended EventType members."""
from __future__ import annotations

import pytest

from breadmind.core.events import Event, EventBus, EventType


@pytest.fixture
def bus():
    return EventBus()


# All 15 new event types
EXTENDED_EVENTS = [
    EventType.INSTRUCTIONS_LOADED,
    EventType.POST_TOOL_USE_FAILURE,
    EventType.STOP_FAILURE,
    EventType.SUBAGENT_START_HOOK,
    EventType.TASK_CREATED,
    EventType.TASK_COMPLETED,
    EventType.TEAMMATE_IDLE,
    EventType.CONFIG_CHANGE,
    EventType.CWD_CHANGED,
    EventType.FILE_CHANGED,
    EventType.POST_COMPACT,
    EventType.WORKTREE_CREATE,
    EventType.WORKTREE_REMOVE,
    EventType.NOTIFICATION,
    EventType.ELICITATION,
]


def test_all_extended_events_are_str_enum_members():
    """Each new EventType is a string enum member with a non-empty value."""
    for evt in EXTENDED_EVENTS:
        assert isinstance(evt, EventType)
        assert isinstance(evt.value, str)
        assert len(evt.value) > 0


def test_extended_event_values_are_unique():
    """No two EventType members share the same value."""
    all_values = [e.value for e in EventType]
    assert len(all_values) == len(set(all_values))


async def test_publish_instructions_loaded(bus):
    received = []
    bus.subscribe(EventType.INSTRUCTIONS_LOADED, lambda d: received.append(d))
    await bus.publish(Event(type=EventType.INSTRUCTIONS_LOADED, data={"files": ["CLAUDE.md"]}))
    assert len(received) == 1
    assert received[0]["files"] == ["CLAUDE.md"]


async def test_publish_post_tool_use_failure(bus):
    received = []
    bus.subscribe(EventType.POST_TOOL_USE_FAILURE, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.POST_TOOL_USE_FAILURE,
        data={"tool": "shell_exec", "error": "timeout"},
    ))
    assert received[0]["tool"] == "shell_exec"


async def test_publish_stop_failure(bus):
    received = []
    bus.subscribe(EventType.STOP_FAILURE, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.STOP_FAILURE,
        data={"reason": "api_error", "status_code": 500},
    ))
    assert received[0]["reason"] == "api_error"


async def test_publish_task_events(bus):
    created = []
    completed = []
    bus.subscribe(EventType.TASK_CREATED, lambda d: created.append(d))
    bus.subscribe(EventType.TASK_COMPLETED, lambda d: completed.append(d))

    await bus.publish(Event(type=EventType.TASK_CREATED, data={"task_id": "t1"}))
    await bus.publish(Event(type=EventType.TASK_COMPLETED, data={"task_id": "t1"}))

    assert len(created) == 1
    assert len(completed) == 1
    assert created[0]["task_id"] == "t1"


async def test_publish_config_change(bus):
    received = []
    bus.subscribe(EventType.CONFIG_CHANGE, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.CONFIG_CHANGE,
        data={"key": "llm.provider", "old": "claude", "new": "gemini"},
    ))
    assert received[0]["key"] == "llm.provider"


async def test_publish_cwd_changed(bus):
    received = []
    bus.subscribe(EventType.CWD_CHANGED, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.CWD_CHANGED,
        data={"old_cwd": "/a", "new_cwd": "/b"},
    ))
    assert received[0]["new_cwd"] == "/b"


async def test_publish_file_changed(bus):
    received = []
    bus.subscribe(EventType.FILE_CHANGED, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.FILE_CHANGED,
        data={"path": "src/main.py", "action": "modified"},
    ))
    assert received[0]["path"] == "src/main.py"


async def test_publish_post_compact(bus):
    received = []
    bus.subscribe(EventType.POST_COMPACT, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.POST_COMPACT,
        data={"level": 3, "tokens_saved": 5000},
    ))
    assert received[0]["level"] == 3


async def test_publish_worktree_events(bus):
    created = []
    removed = []
    bus.subscribe(EventType.WORKTREE_CREATE, lambda d: created.append(d))
    bus.subscribe(EventType.WORKTREE_REMOVE, lambda d: removed.append(d))

    await bus.publish(Event(type=EventType.WORKTREE_CREATE, data={"branch": "feat-x"}))
    await bus.publish(Event(type=EventType.WORKTREE_REMOVE, data={"branch": "feat-x"}))

    assert len(created) == 1
    assert len(removed) == 1


async def test_publish_notification(bus):
    received = []
    bus.subscribe(EventType.NOTIFICATION, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.NOTIFICATION,
        data={"message": "Deploy complete", "severity": "info"},
    ))
    assert received[0]["message"] == "Deploy complete"


async def test_publish_elicitation(bus):
    received = []
    bus.subscribe(EventType.ELICITATION, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.ELICITATION,
        data={"server": "mcp-git", "prompt": "Enter token"},
    ))
    assert received[0]["server"] == "mcp-git"


async def test_publish_teammate_idle(bus):
    received = []
    bus.subscribe(EventType.TEAMMATE_IDLE, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.TEAMMATE_IDLE,
        data={"agent_id": "worker-1"},
    ))
    assert received[0]["agent_id"] == "worker-1"


async def test_publish_subagent_start_hook(bus):
    received = []
    bus.subscribe(EventType.SUBAGENT_START_HOOK, lambda d: received.append(d))
    await bus.publish(Event(
        type=EventType.SUBAGENT_START_HOOK,
        data={"subagent_type": "browser", "task": "screenshot"},
    ))
    assert received[0]["subagent_type"] == "browser"


async def test_global_subscriber_receives_extended_events(bus):
    """Global (*) subscribers should receive extended events too."""
    received = []
    bus.subscribe_all(lambda d: received.append(d))
    await bus.publish(Event(type=EventType.ELICITATION, data={"x": 1}))
    assert len(received) == 1
