import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.tools.mcp_client import MCPClientManager, MCPServerInfo, _StdioServerConfig
from breadmind.tools.mcp_protocol import encode_message


@pytest.fixture
def manager():
    return MCPClientManager()


def test_manager_initial_state(manager):
    assert manager.list_servers_sync() == []


def test_manager_accepts_call_timeout():
    m = MCPClientManager(call_timeout=60)
    assert m._call_timeout == 60


@pytest.mark.asyncio
async def test_stop_server_graceful(manager):
    manager._servers["test"] = MCPServerInfo(
        name="test", transport="stdio", status="running", tools=[], source="config"
    )
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()
    manager._processes["test"] = mock_proc

    await manager.stop_server("test")
    assert manager._servers["test"].status == "stopped"
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called()
    # Process ref cleaned up
    assert "test" not in manager._processes


@pytest.mark.asyncio
async def test_stop_server_forceful_on_timeout(manager):
    """If server doesn't stop within 5 seconds after SIGTERM, SIGKILL is sent."""
    manager._servers["test"] = MCPServerInfo(
        name="test", transport="stdio", status="running", tools=[], source="config"
    )
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    call_count = 0

    async def slow_wait():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()

    mock_proc.wait = slow_wait
    manager._processes["test"] = mock_proc

    await manager.stop_server("test")
    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()
    assert manager._servers["test"].status == "stopped"


@pytest.mark.asyncio
async def test_stop_all(manager):
    for name in ["a", "b"]:
        manager._servers[name] = MCPServerInfo(
            name=name, transport="stdio", status="running", tools=[], source="config"
        )
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        manager._processes[name] = mock_proc

    await manager.stop_all()
    assert all(s.status == "stopped" for s in manager._servers.values())


@pytest.mark.asyncio
async def test_health_check_no_server(manager):
    result = await manager.health_check("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_call_tool_server_not_running(manager):
    result = await manager.call_tool("nonexistent", "tool", {})
    assert result.success is False
    assert "not running" in result.output


@pytest.mark.asyncio
async def test_list_servers(manager):
    manager._servers["test"] = MCPServerInfo(
        name="test", transport="sse", status="running", tools=["tool_a"], source="config"
    )
    servers = await manager.list_servers()
    assert len(servers) == 1
    assert servers[0].name == "test"


@pytest.mark.asyncio
async def test_call_tool_timeout(manager):
    """call_tool returns timeout error when server doesn't respond."""
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()

    async def slow_read(proc):
        await asyncio.sleep(100)

    m = MCPClientManager(call_timeout=1)
    m._processes["srv"] = mock_proc
    m._servers["srv"] = MCPServerInfo(
        name="srv", transport="stdio", status="running",
    )

    with patch.object(m, "_send_stdio", AsyncMock()):
        with patch.object(m, "_read_stdio", side_effect=slow_read):
            result = await m.call_tool("srv", "tool", {})

    assert result.success is False
    assert "timeout" in result.output.lower()


@pytest.mark.asyncio
async def test_auto_restart_on_dead_server(manager):
    """call_tool tries to restart a dead stdio server."""
    manager._servers["srv"] = MCPServerInfo(
        name="srv", transport="stdio", status="running",
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 1  # dead
    manager._processes["srv"] = mock_proc
    manager._restart_counts["srv"] = 0
    manager._server_configs["srv"] = _StdioServerConfig(
        command="echo", args=[], env=None, source="config",
    )

    # Mock start_stdio_server to simulate restart
    async def fake_start(name, cmd, args, env=None, source="config"):
        new_proc = MagicMock()
        new_proc.returncode = None
        new_proc.stdin = MagicMock()
        new_proc.stdin.write = MagicMock()
        new_proc.stdin.drain = AsyncMock()
        manager._processes[name] = new_proc
        manager._servers[name].status = "running"
        return []

    with patch.object(manager, "start_stdio_server", side_effect=fake_start):
        # Also patch call_tool's actual IO to return a successful result
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}}
        with patch.object(manager, "_read_stdio", AsyncMock(return_value=resp)):
            with patch.object(manager, "_send_stdio", AsyncMock()):
                result = await manager.call_tool("srv", "tool", {})

    assert result.success is True
    assert manager._restart_counts["srv"] == 1


@pytest.mark.asyncio
async def test_auto_restart_max_attempts_exceeded(manager):
    """No restart when max attempts exhausted."""
    manager._servers["srv"] = MCPServerInfo(
        name="srv", transport="stdio", status="running",
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    manager._processes["srv"] = mock_proc
    manager._restart_counts["srv"] = 3  # already at max
    manager._server_configs["srv"] = _StdioServerConfig(
        command="echo", args=[], env=None, source="config",
    )

    result = await manager.call_tool("srv", "tool", {})
    assert result.success is False
    assert "not running" in result.output


@pytest.mark.asyncio
async def test_detailed_health_check_alive_and_responsive(manager):
    mock_proc = MagicMock()
    mock_proc.returncode = None
    manager._processes["srv"] = mock_proc

    resp = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "a"}, {"name": "b"}]}}

    with patch.object(manager, "_read_stdio", AsyncMock(return_value=resp)):
        with patch.object(manager, "_send_stdio", AsyncMock()):
            result = await manager.detailed_health_check("srv")

    assert result["alive"] is True
    assert result["responsive"] is True
    assert result["tools_count"] == 2


@pytest.mark.asyncio
async def test_detailed_health_check_dead_server(manager):
    result = await manager.detailed_health_check("nonexistent")
    assert result["alive"] is False
    assert result["responsive"] is False
    assert result["tools_count"] == 0


@pytest.mark.asyncio
async def test_detailed_health_check_unresponsive(manager):
    mock_proc = MagicMock()
    mock_proc.returncode = None
    manager._processes["srv"] = mock_proc

    with patch.object(manager, "_send_stdio", AsyncMock(side_effect=Exception("fail"))):
        result = await manager.detailed_health_check("srv")

    assert result["alive"] is True
    assert result["responsive"] is False


@pytest.mark.asyncio
async def test_read_stdio_buffered():
    """Test that _read_stdio uses readline and parses headers correctly."""
    manager = MCPClientManager()

    body_dict = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    body_bytes = json.dumps(body_dict).encode("utf-8")
    header = f"Content-Length: {len(body_bytes)}\r\n\r\n".encode("utf-8")
    full_data = header + body_bytes

    mock_stdout = AsyncMock()
    # Simulate readline returning the header line, then the blank line
    mock_stdout.readline = AsyncMock(side_effect=[
        b"Content-Length: " + str(len(body_bytes)).encode() + b"\r\n",
        b"\r\n",
    ])
    mock_stdout.readexactly = AsyncMock(return_value=body_bytes)

    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout

    result = await manager._read_stdio(mock_proc)
    assert result == body_dict


@pytest.mark.asyncio
async def test_read_stdio_rejects_oversized_message():
    """Messages exceeding 10MB are rejected."""
    manager = MCPClientManager()

    huge_length = 11 * 1024 * 1024
    mock_stdout = AsyncMock()
    mock_stdout.readline = AsyncMock(side_effect=[
        f"Content-Length: {huge_length}\r\n".encode(),
        b"\r\n",
    ])

    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout

    with pytest.raises(ValueError, match="too large"):
        await manager._read_stdio(mock_proc)


@pytest.mark.asyncio
async def test_read_stdio_missing_header():
    """Missing Content-Length header raises ValueError."""
    manager = MCPClientManager()

    mock_stdout = AsyncMock()
    mock_stdout.readline = AsyncMock(side_effect=[
        b"X-Custom: something\r\n",
        b"\r\n",
    ])

    mock_proc = MagicMock()
    mock_proc.stdout = mock_stdout

    with pytest.raises(ValueError, match="Missing Content-Length"):
        await manager._read_stdio(mock_proc)
