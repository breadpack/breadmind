"""Tests for Commander WebSocket hub."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from breadmind.network.commander import Commander
from breadmind.network.protocol import MessageType, create_message
from breadmind.network.registry import AgentRegistry, AgentStatus


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def commander(registry):
    return Commander(
        registry=registry,
        llm_provider=AsyncMock(),
        session_key=b"test-key-32-bytes-long-enough!!",
    )


@pytest.mark.asyncio
async def test_handle_registration(commander, registry):
    msg = create_message(
        type=MessageType.HEARTBEAT,
        source="worker-1",
        target="commander",
        payload={"environment": {"os": "linux"}, "host": "192.168.1.10"},
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    agent = registry.get("worker-1")
    assert agent is not None


@pytest.mark.asyncio
async def test_handle_heartbeat_updates_metrics(commander, registry):
    registry.register("worker-1", host="h1")
    registry.set_status("worker-1", AgentStatus.ACTIVE)
    msg = create_message(
        type=MessageType.HEARTBEAT,
        source="worker-1",
        target="commander",
        payload={"cpu": 0.3, "memory": 0.5, "disk": 0.2, "queue_size": 0},
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    agent = registry.get("worker-1")
    assert agent.last_metrics["cpu"] == 0.3


@pytest.mark.asyncio
async def test_handle_task_result(commander, registry):
    registry.register("worker-1", host="h1")
    msg = create_message(
        type=MessageType.TASK_RESULT,
        source="worker-1",
        target="commander",
        payload={
            "task_id": "t1",
            "status": "success",
            "output": "all pods healthy",
            "metrics": {"duration_ms": 500},
        },
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    assert "t1" in commander.completed_tasks


@pytest.mark.asyncio
async def test_handle_llm_request_proxies_to_provider(commander):
    commander._llm_provider.chat = AsyncMock(return_value=MagicMock(
        content="restart the pod",
        tool_calls=[],
        usage=MagicMock(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    ))
    msg = create_message(
        type=MessageType.LLM_REQUEST,
        source="worker-1",
        target="commander",
        payload={
            "messages": [{"role": "user", "content": "check pods"}],
            "tools": [],
        },
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    ws_mock.send.assert_called_once()
    sent_raw = ws_mock.send.call_args[0][0]
    sent = json.loads(sent_raw)
    assert sent["type"] == "llm_response"


@pytest.mark.asyncio
async def test_dispatch_task_to_worker(commander, registry):
    registry.register("worker-1", host="h1")
    registry.set_status("worker-1", AgentStatus.ACTIVE)
    ws_mock = AsyncMock()
    commander._connections["worker-1"] = ws_mock
    await commander.dispatch_task(
        agent_id="worker-1",
        task_type="on_demand",
        params={"command": "kubectl get pods"},
    )
    ws_mock.send.assert_called_once()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["type"] == "task_assign"


@pytest.mark.asyncio
async def test_dispatch_role_update(commander, registry):
    registry.register("worker-1", host="h1")
    ws_mock = AsyncMock()
    commander._connections["worker-1"] = ws_mock
    from breadmind.network.registry import RoleDefinition
    role = RoleDefinition(name="test", tools=["shell_exec"], schedules=[], policies={})
    await commander.send_role_update("worker-1", role)
    ws_mock.send.assert_called_once()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["type"] == "role_update"
