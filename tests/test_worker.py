# tests/test_worker.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.network.worker import Worker, WorkerState
from breadmind.network.protocol import MessageType, create_message

SESSION_KEY = b"test-key-32-bytes-long-enough!!"

@pytest.fixture
def tool_registry():
    reg = MagicMock()
    reg.execute = AsyncMock(return_value=MagicMock(success=True, output="ok"))
    reg.get_definitions = MagicMock(return_value=[])
    return reg

@pytest.fixture
def worker(tool_registry):
    return Worker(
        agent_id="worker-1",
        commander_url="wss://localhost:8081/ws/agent/worker-1",
        session_key=SESSION_KEY,
        tool_registry=tool_registry,
    )

def test_worker_initial_state(worker):
    assert worker.state == WorkerState.STARTING

@pytest.mark.asyncio
async def test_handle_task_assign_executes_locally(worker, tool_registry):
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={
            "task_id": "t1",
            "idempotency_key": "idem-1",
            "type": "on_demand",
            "params": {"tool": "shell_exec", "arguments": {"command": "ls"}},
        },
    )
    ws_mock = AsyncMock()
    worker._ws = ws_mock
    await worker.handle_message(msg)
    tool_registry.execute.assert_called_once_with("shell_exec", {"command": "ls"})
    ws_mock.send.assert_called_once()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["type"] == "task_result"
    assert sent["payload"]["task_id"] == "t1"
    assert sent["payload"]["status"] == "success"

@pytest.mark.asyncio
async def test_handle_role_update_stores_role(worker):
    msg = create_message(
        type=MessageType.ROLE_UPDATE,
        source="commander",
        target="worker-1",
        payload={
            "role": {
                "name": "monitor",
                "tools": ["shell_exec"],
                "schedules": [{"type": "cron", "expr": "*/5 * * * *", "task": "check"}],
                "policies": {"auto_actions": [], "require_approval": [], "blocked": []},
            },
        },
    )
    await worker.handle_message(msg)
    assert "monitor" in worker.roles

@pytest.mark.asyncio
async def test_handle_command_restart(worker):
    msg = create_message(
        type=MessageType.COMMAND,
        source="commander",
        target="worker-1",
        payload={"action": "restart"},
    )
    with patch.object(worker, "_restart", new_callable=AsyncMock) as mock_restart:
        await worker.handle_message(msg)
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_blocked_tool_not_executed(worker, tool_registry):
    worker.roles["test"] = {
        "tools": ["file_read"],
        "policies": {"blocked": ["shell_exec"], "auto_actions": [], "require_approval": []},
    }
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={
            "task_id": "t2",
            "idempotency_key": "idem-2",
            "type": "on_demand",
            "params": {"tool": "shell_exec", "arguments": {"command": "rm -rf /"}},
        },
    )
    ws_mock = AsyncMock()
    worker._ws = ws_mock
    await worker.handle_message(msg)
    tool_registry.execute.assert_not_called()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["payload"]["status"] == "failure"
    assert "blocked" in sent["payload"]["output"].lower()

@pytest.mark.asyncio
async def test_offline_queue_stores_when_disconnected(worker, tool_registry):
    worker._ws = None  # Disconnected
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={
            "task_id": "t3",
            "idempotency_key": "idem-3",
            "type": "scheduled",
            "params": {"tool": "shell_exec", "arguments": {"command": "uptime"}},
        },
    )
    await worker.handle_message(msg)
    tool_registry.execute.assert_called_once()
    assert len(worker._offline_queue) == 1
    assert worker._offline_queue[0]["task_id"] == "t3"
