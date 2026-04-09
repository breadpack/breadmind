"""Tests for CompanionRuntime."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from breadmind.companion.config import CompanionConfig
from breadmind.companion.runtime import CompanionRuntime, CompanionState
from breadmind.network.protocol import MessageType, create_message
from tests.companion.conftest import MockPlatformAdapter


@pytest.fixture
def runtime():
    config = CompanionConfig(
        commander_url="ws://localhost:8081/ws/agent",
        agent_id="test-companion-1",
        device_name="test-device",
    )
    adapter = MockPlatformAdapter()
    rt = CompanionRuntime(config=config, platform_adapter=adapter)
    return rt


async def test_build_environment(runtime):
    env = await runtime._build_environment()
    assert env["agent_type"] == "companion"
    assert env["device_name"] == "test-device"
    assert "os" in env
    assert "capabilities" in env


async def test_build_metrics(runtime):
    metrics = await runtime._build_metrics()
    assert "cpu" in metrics
    assert "memory" in metrics
    assert 0 <= metrics["cpu"] <= 1
    assert 0 <= metrics["memory"] <= 1


async def test_handle_task_unknown_tool(runtime):
    """Unknown tool should return failure."""
    runtime._ws = AsyncMock()
    runtime.register_tools({})

    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="test-companion-1",
        payload={
            "task_id": "t1",
            "params": {"tool": "nonexistent_tool", "arguments": {}},
        },
    )
    await runtime._handle_task(msg)
    assert "t1" in runtime._task_history
    assert runtime._task_history["t1"]["status"] == "failure"
    assert "Unknown" in runtime._task_history["t1"]["output"]


async def test_handle_task_permission_denied(runtime):
    """Tool that's not permitted should return failure."""
    runtime._ws = AsyncMock()

    async def dummy_tool(plat, perms, args):
        return {"ok": True}

    runtime.register_tools({"companion_power": dummy_tool})
    # companion_power is denied by default

    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="test-companion-1",
        payload={
            "task_id": "t2",
            "params": {"tool": "companion_power", "arguments": {"action": "sleep"}},
        },
    )
    await runtime._handle_task(msg)
    assert runtime._task_history["t2"]["status"] == "failure"
    assert "Permission denied" in runtime._task_history["t2"]["output"]


async def test_handle_task_success(runtime):
    """Allowed tool should execute and return success."""
    runtime._ws = AsyncMock()

    async def mock_system_info(plat, perms, args):
        return {"os": "TestOS"}

    runtime.register_tools({"companion_system_info": mock_system_info})

    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="test-companion-1",
        payload={
            "task_id": "t3",
            "params": {"tool": "companion_system_info", "arguments": {}},
        },
    )
    await runtime._handle_task(msg)
    assert runtime._task_history["t3"]["status"] == "success"
    assert runtime._task_history["t3"]["output"]["os"] == "TestOS"


async def test_stop(runtime):
    runtime.state = CompanionState.CONNECTED
    await runtime.stop()
    assert runtime.state == CompanionState.STOPPED
    assert runtime._stop_event.is_set()
