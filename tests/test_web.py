import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from breadmind.web.app import WebApp

@pytest.fixture
def web_app():
    mock_registry = MagicMock()
    mock_registry.get_all_definitions.return_value = []
    mock_registry.get_tool_source.return_value = "builtin"

    mock_mcp = MagicMock()
    mock_mcp.list_servers = AsyncMock(return_value=[])

    app = WebApp(tool_registry=mock_registry, mcp_manager=mock_mcp)
    return app

@pytest.fixture
def client(web_app):
    return TestClient(web_app.app)

def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data

def test_tools_endpoint(client):
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    assert "tools" in resp.json()

def test_mcp_servers_endpoint(client):
    resp = client.get("/api/mcp/servers")
    assert resp.status_code == 200
    assert "servers" in resp.json()

def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "BreadMind" in resp.text

def test_tools_with_data():
    from breadmind.llm.base import ToolDefinition
    mock_registry = MagicMock()
    mock_registry.get_all_definitions.return_value = [
        ToolDefinition(name="shell_exec", description="Execute shell", parameters={}),
    ]
    mock_registry.get_tool_source.return_value = "builtin"
    app = WebApp(tool_registry=mock_registry)
    client = TestClient(app.app)
    resp = client.get("/api/tools")
    tools = resp.json()["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "shell_exec"
