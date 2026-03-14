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

    app = WebApp(
        message_handler=AsyncMock(return_value="test response"),
        tool_registry=mock_registry,
        mcp_manager=mock_mcp,
    )
    return app

@pytest.fixture
def client(web_app):
    return TestClient(web_app.app)

def test_health_endpoint_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "components" in data
    assert data["components"]["agent"] is True

def test_health_endpoint_no_handler():
    app = WebApp()
    client = TestClient(app.app)
    resp = client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["components"]["agent"] is False

def test_health_endpoint_monitoring_status():
    mock_engine = MagicMock()
    mock_engine.get_status.return_value = {"running": True, "rules_count": 2, "tasks_count": 1}
    app = WebApp(message_handler=lambda m, **kw: "ok", monitoring_engine=mock_engine)
    client = TestClient(app.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["components"]["monitoring"] is True

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
    app = WebApp(message_handler=lambda m, **kw: "ok", tool_registry=mock_registry)
    client = TestClient(app.app)
    resp = client.get("/api/tools")
    tools = resp.json()["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "shell_exec"

def test_config_endpoint():
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm" in data
    assert data["llm"]["default_provider"] == "claude"

def test_safety_endpoint():
    safety = {"blacklist": {"k8s": ["delete_ns"]}, "require_approval": ["shell_exec"]}
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_config=safety)
    client = TestClient(app.app)
    resp = client.get("/api/safety")
    assert resp.status_code == 200
    assert "blacklist" in resp.json()

def test_monitoring_events_endpoint():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/monitoring/events")
    assert resp.status_code == 200
    assert "events" in resp.json()

def test_monitoring_status_endpoint():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "rules" in data

def test_monitoring_status_with_engine():
    mock_engine = MagicMock()
    mock_engine.get_status.return_value = {"running": True, "rules_count": 3, "tasks_count": 2}
    app = WebApp(message_handler=lambda m, **kw: "ok", monitoring_engine=mock_engine)
    client = TestClient(app.app)
    resp = client.get("/api/monitoring/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["rules"] == 3

# --- New API endpoint tests ---

def test_usage_endpoint_no_agent():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/usage")
    assert resp.status_code == 200
    assert resp.json() == {"usage": {}}

def test_usage_endpoint_with_agent():
    mock_agent = MagicMock()
    mock_agent.get_usage.return_value = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_tokens": 200,
        "total_cost": 0.0123,
    }
    app = WebApp(message_handler=lambda m, **kw: "ok", agent=mock_agent)
    client = TestClient(app.app)
    resp = client.get("/api/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["usage"]["input_tokens"] == 1000
    assert data["usage"]["output_tokens"] == 500
    assert data["usage"]["total_cost"] == 0.0123

def test_audit_endpoint_no_logger():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    assert resp.json() == {"entries": []}

def test_audit_endpoint_with_logger():
    mock_logger = MagicMock()
    mock_logger.get_recent.return_value = [
        {"action": "shell_exec", "user": "admin", "timestamp": "2026-03-14T10:00:00"},
        {"action": "file_read", "user": "admin", "timestamp": "2026-03-14T10:01:00"},
    ]
    app = WebApp(message_handler=lambda m, **kw: "ok", audit_logger=mock_logger)
    client = TestClient(app.app)
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 2
    assert entries[0]["action"] == "shell_exec"

def test_metrics_endpoint_no_collector():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert resp.json() == {"metrics": {}}

def test_metrics_endpoint_with_collector():
    mock_collector = MagicMock()
    mock_collector.get_summary.return_value = {
        "shell_exec": {"call_count": 10, "success_count": 9, "avg_duration_ms": 150.5},
        "file_read": {"call_count": 5, "success_count": 5, "avg_duration_ms": 20.0},
    }
    app = WebApp(message_handler=lambda m, **kw: "ok", metrics_collector=mock_collector)
    client = TestClient(app.app)
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert "shell_exec" in metrics
    assert metrics["shell_exec"]["call_count"] == 10

def test_approvals_endpoint_no_agent():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/approvals")
    assert resp.status_code == 200
    assert resp.json() == {"approvals": []}

def test_approvals_endpoint_with_agent():
    mock_agent = MagicMock()
    mock_agent.get_pending_approvals.return_value = [
        {"id": "abc123", "tool_name": "shell_exec", "arguments": {"command": "rm -rf /"}},
    ]
    app = WebApp(message_handler=lambda m, **kw: "ok", agent=mock_agent)
    client = TestClient(app.app)
    resp = client.get("/api/approvals")
    assert resp.status_code == 200
    approvals = resp.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["tool_name"] == "shell_exec"

def test_approve_tool_with_agent():
    mock_agent = MagicMock()
    mock_agent.approve_tool.return_value = True
    app = WebApp(message_handler=lambda m, **kw: "ok", agent=mock_agent)
    client = TestClient(app.app)
    resp = client.post("/api/approvals/abc123/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["approval_id"] == "abc123"
    mock_agent.approve_tool.assert_called_once_with("abc123")

def test_approve_tool_no_agent():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/approvals/abc123/approve")
    assert resp.status_code == 404

def test_deny_tool_with_agent():
    mock_agent = MagicMock()
    mock_agent.deny_tool.return_value = True
    app = WebApp(message_handler=lambda m, **kw: "ok", agent=mock_agent)
    client = TestClient(app.app)
    resp = client.post("/api/approvals/abc123/deny")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "denied"
    assert data["approval_id"] == "abc123"
    mock_agent.deny_tool.assert_called_once_with("abc123")

def test_deny_tool_no_agent():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/approvals/abc123/deny")
    assert resp.status_code == 404
