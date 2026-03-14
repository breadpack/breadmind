import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.mcp_client import MCPClientManager, MCPServerInfo

@pytest.fixture
def manager():
    return MCPClientManager()

def test_manager_initial_state(manager):
    assert manager.list_servers_sync() == []

@pytest.mark.asyncio
async def test_stop_server(manager):
    manager._servers["test"] = MCPServerInfo(
        name="test", transport="stdio", status="running", tools=[], source="config"
    )
    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()
    manager._processes["test"] = mock_proc

    await manager.stop_server("test")
    assert manager._servers["test"].status == "stopped"
    mock_proc.terminate.assert_called_once()

@pytest.mark.asyncio
async def test_stop_all(manager):
    for name in ["a", "b"]:
        manager._servers[name] = MCPServerInfo(
            name=name, transport="stdio", status="running", tools=[], source="config"
        )
        mock_proc = MagicMock()
        mock_proc.terminate = MagicMock()
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
