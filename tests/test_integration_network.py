"""Integration test: Commander <-> Worker message flow."""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock
from breadmind.network.commander import Commander
from breadmind.network.worker import Worker
from breadmind.network.registry import AgentRegistry, AgentStatus, RoleDefinition
from breadmind.network.protocol import (
    MessageType, create_message, serialize_message, deserialize_message,
)

SESSION_KEY = b"integration-test-key-32-bytes!!"


class FakeWebSocket:
    """Simulates WebSocket for testing Commander <-> Worker flow."""

    def __init__(self, peer: "FakeWebSocket | None" = None):
        self._peer = peer
        self._handler = None
        self.sent: list[str] = []

    def set_peer(self, peer: "FakeWebSocket"):
        self._peer = peer

    def set_handler(self, handler):
        self._handler = handler

    async def send(self, data: str):
        self.sent.append(data)
        if self._peer and self._peer._handler:
            msg = deserialize_message(data, SESSION_KEY)
            await self._peer._handler(msg)


@pytest.fixture
def registry():
    return AgentRegistry()

@pytest.fixture
def commander(registry):
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=MagicMock(
        content="all good",
        tool_calls=[],
        usage=MagicMock(input_tokens=5, output_tokens=3),
        stop_reason="end_turn",
    ))
    return Commander(registry=registry, llm_provider=provider, session_key=SESSION_KEY)

@pytest.fixture
def tool_registry():
    reg = MagicMock()
    reg.execute = AsyncMock(return_value=MagicMock(success=True, output="pods healthy"))
    return reg

@pytest.fixture
def worker(tool_registry):
    return Worker(
        agent_id="test-worker",
        commander_url="wss://localhost:8081/ws/agent/test-worker",
        session_key=SESSION_KEY,
        tool_registry=tool_registry,
    )

@pytest.mark.asyncio
async def test_full_task_flow(commander, worker, registry):
    """Commander dispatches task -> Worker executes -> Commander receives result."""
    # Set up fake WebSocket pair
    cmd_ws = FakeWebSocket()
    worker_ws = FakeWebSocket()
    cmd_ws.set_peer(worker_ws)
    worker_ws.set_peer(cmd_ws)

    # Wire handlers
    worker_ws.set_handler(worker.handle_message)
    cmd_ws.set_handler(lambda msg: commander.handle_message(msg, cmd_ws, "test-worker"))

    # Register worker
    registry.register("test-worker", host="192.168.1.10")
    registry.set_status("test-worker", AgentStatus.ACTIVE)
    commander.add_connection("test-worker", cmd_ws)
    worker._ws = worker_ws

    # Dispatch task
    task_id = await commander.dispatch_task(
        agent_id="test-worker",
        task_type="on_demand",
        params={"tool": "shell_exec", "arguments": {"command": "kubectl get pods"}},
    )

    # Verify worker received and executed
    assert len(cmd_ws.sent) == 1  # task_assign
    assert len(worker_ws.sent) == 1  # task_result

    # Verify commander got the result
    assert task_id in commander.completed_tasks
    assert commander.completed_tasks[task_id]["status"] == "success"
    assert commander.completed_tasks[task_id]["output"] == "pods healthy"

@pytest.mark.asyncio
async def test_role_assignment_flow(commander, worker, registry):
    """Commander assigns role -> Worker stores it."""
    registry.register("test-worker", host="h1")
    cmd_ws = FakeWebSocket()
    worker_ws = FakeWebSocket()
    cmd_ws.set_peer(worker_ws)
    worker_ws.set_handler(worker.handle_message)
    commander.add_connection("test-worker", cmd_ws)
    worker._ws = worker_ws

    role = RoleDefinition(
        name="k8s-monitor",
        tools=["shell_exec", "file_read"],
        schedules=[{"type": "cron", "expr": "*/5 * * * *", "task": "check"}],
        policies={"auto_actions": ["restart_pod"], "require_approval": [], "blocked": ["delete_namespace"]},
    )
    await commander.send_role_update("test-worker", role)

    assert "k8s-monitor" in worker.roles
    assert worker.roles["k8s-monitor"]["tools"] == ["shell_exec", "file_read"]

@pytest.mark.asyncio
async def test_offline_queue_and_sync(commander, worker, registry, tool_registry):
    """Worker queues result offline -> syncs on reconnect."""
    registry.register("test-worker", host="h1")

    # Worker is disconnected
    worker._ws = None

    # Execute task while offline
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="test-worker",
        payload={
            "task_id": "offline-t1",
            "idempotency_key": "idem-offline-1",
            "type": "scheduled",
            "params": {"tool": "shell_exec", "arguments": {"command": "uptime"}},
        },
    )
    await worker.handle_message(msg)
    assert len(worker._offline_queue) == 1

    # Reconnect and sync
    cmd_ws = FakeWebSocket()
    worker_ws = FakeWebSocket()
    cmd_ws.set_handler(lambda msg: commander.handle_message(msg, cmd_ws, "test-worker"))
    worker._ws = worker_ws

    await worker.sync_offline_queue()
    assert len(worker._offline_queue) == 0
    assert len(worker_ws.sent) == 1  # sync message
