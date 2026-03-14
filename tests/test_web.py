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


# --- Config editing endpoint tests ---

def test_get_api_keys_status_empty():
    """Test GET /api/config/api-keys when no keys are set."""
    import os
    # Ensure keys are not set
    for k in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
        os.environ.pop(k, None)
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/api-keys")
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    for key_name in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
        assert data["keys"][key_name]["set"] is False
        assert data["keys"][key_name]["masked"] == ""


def test_get_api_keys_status_with_key():
    """Test GET /api/config/api-keys returns masked values when keys are set."""
    import os
    os.environ["GEMINI_API_KEY"] = "AIzaSyD1234567890abcdef"
    try:
        app = WebApp(message_handler=lambda m, **kw: "ok")
        client = TestClient(app.app)
        resp = client.get("/api/config/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        gemini = data["keys"]["GEMINI_API_KEY"]
        assert gemini["set"] is True
        assert gemini["masked"] == "AIzaSyD1***"
        assert "1234567890" not in gemini["masked"]
    finally:
        os.environ.pop("GEMINI_API_KEY", None)


def test_post_api_key_saves(tmp_path, monkeypatch):
    """Test POST /api/config/api-keys saves the key after validation."""
    import os as _os
    import breadmind.config as config_module
    # Mock save_env_var to avoid writing to real .env
    saved = {}
    def mock_save(k, v):
        saved[k] = v
        _os.environ[k] = v
    monkeypatch.setattr(config_module, "save_env_var", mock_save)
    # Mock aiohttp to skip real API validation
    import aiohttp
    from unittest.mock import AsyncMock, MagicMock, patch
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: mock_session)
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/api-keys", json={
        "key_name": "ANTHROPIC_API_KEY",
        "value": "sk-ant-api03-abcdefgh12345678"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["masked"] == "sk-ant-a***"
    assert saved["ANTHROPIC_API_KEY"] == "sk-ant-api03-abcdefgh12345678"
    # Clean up
    _os.environ.pop("ANTHROPIC_API_KEY", None)


def test_post_api_key_validation_failure(monkeypatch):
    """Test POST /api/config/api-keys rejects invalid keys after validation."""
    import aiohttp
    from unittest.mock import AsyncMock, MagicMock
    mock_resp = MagicMock()
    mock_resp.status = 401
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: mock_session)

    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/api-keys", json={
        "key_name": "ANTHROPIC_API_KEY",
        "value": "invalid-key-12345678"
    })
    assert resp.status_code == 400
    assert "validation failed" in resp.json()["error"].lower()


def test_post_api_key_invalid_name():
    """Test POST /api/config/api-keys rejects invalid key names."""
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/api-keys", json={
        "key_name": "INVALID_KEY",
        "value": "some-value"
    })
    assert resp.status_code == 400
    assert "Invalid key name" in resp.json()["error"]


def test_post_api_key_empty_value():
    """Test POST /api/config/api-keys rejects empty values."""
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/api-keys", json={
        "key_name": "ANTHROPIC_API_KEY",
        "value": ""
    })
    assert resp.status_code == 400
    assert "empty" in resp.json()["error"]


def test_post_provider_updates_config():
    """Test POST /api/config/provider updates runtime config."""
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/provider", json={
        "provider": "gemini",
        "model": "gemini-2.0-flash",
        "max_turns": 5,
        "timeout": 60
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert config.llm.default_provider == "gemini"
    assert config.llm.default_model == "gemini-2.0-flash"
    assert config.llm.tool_call_max_turns == 5
    assert config.llm.tool_call_timeout_seconds == 60


def test_post_provider_invalid_provider():
    """Test POST /api/config/provider rejects invalid provider."""
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/provider", json={"provider": "invalid_llm"})
    assert resp.status_code == 400
    assert "Invalid provider" in resp.json()["error"]


def test_post_provider_invalid_max_turns():
    """Test POST /api/config/provider rejects invalid max_turns."""
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/provider", json={"max_turns": -1})
    assert resp.status_code == 400
    assert "max_turns" in resp.json()["error"]


def test_post_mcp_updates_config():
    """Test POST /api/config/mcp updates MCP settings."""
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/mcp", json={
        "auto_discover": False,
        "max_restart_attempts": 5
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert config.mcp.auto_discover is False
    assert config.mcp.max_restart_attempts == 5


# --- Persona endpoint tests ---

def test_get_persona_returns_default():
    """Test GET /api/config/persona returns default persona when none configured."""
    from breadmind.config import AppConfig, DEFAULT_PERSONA
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.get("/api/config/persona")
    assert resp.status_code == 200
    data = resp.json()
    assert "persona" in data
    assert "presets" in data
    assert data["persona"]["name"] == "BreadMind"
    assert data["persona"]["preset"] == "professional"
    assert "professional" in data["presets"]
    assert "friendly" in data["presets"]


def test_post_persona_updates_config():
    """Test POST /api/config/persona updates persona in config."""
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/persona", json={
        "name": "MyBot",
        "preset": "friendly",
        "language": "en",
        "specialties": ["kubernetes"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["persona"]["name"] == "MyBot"
    assert data["persona"]["preset"] == "friendly"
    assert data["persona"]["language"] == "en"
    assert data["persona"]["specialties"] == ["kubernetes"]
    # Config should be updated
    assert config._persona["name"] == "MyBot"


def test_post_persona_with_preset_change():
    """Test POST /api/config/persona with preset change uses preset prompt."""
    from breadmind.config import AppConfig, DEFAULT_PERSONA_PRESETS
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/persona", json={
        "name": "BreadMind",
        "preset": "concise",
        "language": "ko",
        "specialties": [],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"]["system_prompt"] == DEFAULT_PERSONA_PRESETS["concise"]


def test_post_persona_with_custom_prompt():
    """Test POST /api/config/persona with custom system_prompt."""
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    custom = "You are a custom agent with special instructions."
    resp = client.post("/api/config/persona", json={
        "name": "CustomBot",
        "preset": "professional",
        "language": "ja",
        "specialties": ["openwrt"],
        "system_prompt": custom,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"]["system_prompt"] == custom
    assert data["persona"]["name"] == "CustomBot"
    assert data["persona"]["language"] == "ja"


# --- Safety config endpoint tests ---

def test_get_safety_config_with_guard():
    """Test GET /api/config/safety returns data from SafetyGuard."""
    from breadmind.core.safety import SafetyGuard
    guard = SafetyGuard(
        blacklist={"k8s": ["delete_ns"]},
        require_approval=["shell_exec"],
        user_permissions={"alice": ["tool_a"]},
        admin_users=["admin1"],
    )
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_guard=guard)
    client = TestClient(app.app)
    resp = client.get("/api/config/safety")
    assert resp.status_code == 200
    data = resp.json()["safety"]
    assert data["blacklist"] == {"k8s": ["delete_ns"]}
    assert data["require_approval"] == ["shell_exec"]
    assert data["user_permissions"] == {"alice": ["tool_a"]}
    assert data["admin_users"] == ["admin1"]


def test_get_safety_config_fallback_to_raw():
    """Test GET /api/config/safety falls back to safety_config."""
    safety = {"blacklist": {"test": ["t1"]}, "require_approval": ["t2"]}
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_config=safety)
    client = TestClient(app.app)
    resp = client.get("/api/config/safety")
    assert resp.status_code == 200
    data = resp.json()["safety"]
    assert data["blacklist"] == {"test": ["t1"]}


def test_get_safety_config_empty():
    """Test GET /api/config/safety returns empty defaults."""
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/safety")
    assert resp.status_code == 200
    data = resp.json()["safety"]
    assert data["blacklist"] == {}
    assert data["require_approval"] == []


def test_post_blacklist_update():
    """Test POST /api/config/safety/blacklist updates SafetyGuard."""
    from breadmind.core.safety import SafetyGuard
    guard = SafetyGuard()
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_guard=guard)
    client = TestClient(app.app)
    resp = client.post("/api/config/safety/blacklist", json={
        "blacklist": {"network": ["delete_firewall", "reset_dns"]}
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert guard._blacklist == {"network": ["delete_firewall", "reset_dns"]}
    assert "delete_firewall" in guard._flat_blacklist


def test_post_blacklist_invalid_type():
    """Test POST /api/config/safety/blacklist rejects non-dict."""
    from breadmind.core.safety import SafetyGuard
    guard = SafetyGuard()
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_guard=guard)
    client = TestClient(app.app)
    resp = client.post("/api/config/safety/blacklist", json={"blacklist": ["not", "a", "dict"]})
    assert resp.status_code == 400


def test_post_approval_update():
    """Test POST /api/config/safety/approval updates SafetyGuard."""
    from breadmind.core.safety import SafetyGuard
    guard = SafetyGuard()
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_guard=guard)
    client = TestClient(app.app)
    resp = client.post("/api/config/safety/approval", json={
        "require_approval": ["shell_exec", "file_write"]
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert guard._require_approval == {"shell_exec", "file_write"}


def test_post_permissions_update():
    """Test POST /api/config/safety/permissions updates SafetyGuard."""
    from breadmind.core.safety import SafetyGuard
    guard = SafetyGuard()
    app = WebApp(message_handler=lambda m, **kw: "ok", safety_guard=guard)
    client = TestClient(app.app)
    resp = client.post("/api/config/safety/permissions", json={
        "user_permissions": {"bob": ["tool_x", "tool_y"]},
        "admin_users": ["superadmin"],
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert guard._user_permissions == {"bob": ["tool_x", "tool_y"]}
    assert guard._admin_users == ["superadmin"]


def test_post_persona_applies_to_agent():
    """Test POST /api/config/persona applies persona to the agent."""
    from breadmind.config import AppConfig
    config = AppConfig()
    mock_agent = MagicMock()
    mock_agent.set_persona = MagicMock()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config, agent=mock_agent)
    client = TestClient(app.app)
    resp = client.post("/api/config/persona", json={
        "name": "BreadMind",
        "preset": "humorous",
        "language": "ko",
        "specialties": ["kubernetes"],
    })
    assert resp.status_code == 200
    mock_agent.set_persona.assert_called_once()
    call_args = mock_agent.set_persona.call_args[0][0]
    assert call_args["preset"] == "humorous"


# --- Monitoring Rules endpoint tests ---

def test_get_monitoring_rules_no_engine():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/monitoring/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rules"] == []
    assert data["loop_protector"] == {}


def test_get_monitoring_rules_with_engine():
    mock_engine = MagicMock()
    mock_engine.get_rules_config.return_value = [
        {"name": "cpu_check", "description": "Check CPU", "interval_seconds": 60, "enabled": True},
    ]
    mock_engine.get_loop_protector_config.return_value = {"cooldown_minutes": 5, "max_auto_actions": 3}
    app = WebApp(message_handler=lambda m, **kw: "ok", monitoring_engine=mock_engine)
    client = TestClient(app.app)
    resp = client.get("/api/config/monitoring/rules")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rules"]) == 1
    assert data["rules"][0]["name"] == "cpu_check"
    assert data["loop_protector"]["cooldown_minutes"] == 5


def test_post_monitoring_rules_no_engine():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/monitoring/rules", json={"rules": []})
    assert resp.status_code == 503


def test_post_monitoring_rules_with_engine():
    mock_engine = MagicMock()
    app = WebApp(message_handler=lambda m, **kw: "ok", monitoring_engine=mock_engine)
    client = TestClient(app.app)
    resp = client.post("/api/config/monitoring/rules", json={
        "rules": [
            {"name": "cpu_check", "enabled": False, "interval_seconds": 120},
            {"name": "mem_check", "enabled": True},
        ],
        "loop_protector": {"cooldown_minutes": 10, "max_auto_actions": 5},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_engine.disable_rule.assert_called_once_with("cpu_check")
    mock_engine.enable_rule.assert_called_once_with("mem_check")
    mock_engine.update_rule_interval.assert_called_once_with("cpu_check", 120)
    mock_engine.update_loop_protector_config.assert_called_once_with(cooldown_minutes=10, max_auto_actions=5)


# --- Messenger endpoint tests ---

def test_get_messenger_config_no_router():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/messenger")
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed_users"] == {"slack": [], "discord": [], "telegram": []}


def test_get_messenger_config_with_router():
    mock_router = MagicMock()
    mock_router.get_allowed_users.return_value = {"slack": ["user1"], "discord": [], "telegram": ["user2"]}
    app = WebApp(message_handler=lambda m, **kw: "ok", message_router=mock_router)
    client = TestClient(app.app)
    resp = client.get("/api/config/messenger")
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed_users"]["slack"] == ["user1"]
    assert data["allowed_users"]["telegram"] == ["user2"]


def test_post_messenger_config_no_router():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/messenger", json={"allowed_users": {"slack": ["u1"]}})
    assert resp.status_code == 503


def test_post_messenger_config_with_router():
    mock_router = MagicMock()
    app = WebApp(message_handler=lambda m, **kw: "ok", message_router=mock_router)
    client = TestClient(app.app)
    resp = client.post("/api/config/messenger", json={
        "allowed_users": {"slack": ["u1", "u2"], "discord": ["u3"]}
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_router.update_allowed_users.assert_any_call("slack", ["u1", "u2"])
    mock_router.update_allowed_users.assert_any_call("discord", ["u3"])


# --- Memory endpoint tests ---

def test_get_memory_config_no_working_memory():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["memory"]["max_messages_per_session"] == 50
    assert data["memory"]["session_timeout_minutes"] == 30


def test_get_memory_config_with_working_memory():
    mock_wm = MagicMock()
    mock_wm.get_config.return_value = {"max_messages_per_session": 100, "session_timeout_minutes": 60, "active_sessions": 3}
    app = WebApp(message_handler=lambda m, **kw: "ok", working_memory=mock_wm)
    client = TestClient(app.app)
    resp = client.get("/api/config/memory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["memory"]["max_messages_per_session"] == 100
    assert data["memory"]["active_sessions"] == 3


def test_post_memory_config():
    mock_wm = MagicMock()
    app = WebApp(message_handler=lambda m, **kw: "ok", working_memory=mock_wm)
    client = TestClient(app.app)
    resp = client.post("/api/config/memory", json={"max_messages": 200, "timeout_minutes": 45})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_wm.update_config.assert_called_once_with(max_messages=200, timeout_minutes=45)


# --- Tool Security endpoint tests ---

def test_get_tool_security():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/tool-security")
    assert resp.status_code == 200
    data = resp.json()
    assert "security" in data


def test_post_tool_security():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/tool-security", json={
        "dangerous_patterns": ["rm -rf", "mkfs"],
        "allowed_ssh_hosts": ["server1.example.com"],
        "base_directory": "/home/user",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- Timeouts endpoint tests ---

def test_get_timeouts_no_agent():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/config/timeouts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["timeouts"]["tool_timeout"] == 30
    assert data["timeouts"]["chat_timeout"] == 120
    assert data["timeouts"]["max_turns"] == 10


def test_get_timeouts_with_agent():
    mock_agent = MagicMock()
    mock_agent.get_timeouts.return_value = {"tool_timeout": 60, "chat_timeout": 180, "max_turns": 20}
    app = WebApp(message_handler=lambda m, **kw: "ok", agent=mock_agent)
    client = TestClient(app.app)
    resp = client.get("/api/config/timeouts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["timeouts"]["tool_timeout"] == 60
    assert data["timeouts"]["max_turns"] == 20


def test_post_timeouts_with_agent():
    mock_agent = MagicMock()
    app = WebApp(message_handler=lambda m, **kw: "ok", agent=mock_agent)
    client = TestClient(app.app)
    resp = client.post("/api/config/timeouts", json={
        "tool_timeout": 45,
        "chat_timeout": 90,
        "max_turns": 15,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_agent.update_timeouts.assert_called_once_with(tool_timeout=45, chat_timeout=90)
    mock_agent.update_max_turns.assert_called_once_with(15)


def test_post_timeouts_no_agent():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/timeouts", json={"tool_timeout": 45})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- Logging endpoint tests ---

def test_post_logging_valid_level():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/logging", json={"level": "DEBUG"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["level"] == "DEBUG"


def test_post_logging_invalid_level():
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/config/logging", json={"level": "TRACE"})
    assert resp.status_code == 400
    assert "Invalid level" in resp.json()["error"]


def test_post_logging_with_config():
    from breadmind.config import AppConfig
    config = AppConfig()
    app = WebApp(message_handler=lambda m, **kw: "ok", config=config)
    client = TestClient(app.app)
    resp = client.post("/api/config/logging", json={"level": "WARNING"})
    assert resp.status_code == 200
    assert config.logging.level == "WARNING"


# --- Messenger Connection Settings endpoint tests ---

def test_get_messenger_platforms_returns_three():
    """Test GET /api/messenger/platforms returns all 3 platforms."""
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.get("/api/messenger/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert "platforms" in data
    assert "slack" in data["platforms"]
    assert "discord" in data["platforms"]
    assert "telegram" in data["platforms"]
    # Each platform should have name, icon, fields, configured, connected, allowed_users
    for platform_key in ["slack", "discord", "telegram"]:
        p = data["platforms"][platform_key]
        assert "name" in p
        assert "icon" in p
        assert "fields" in p
        assert "configured" in p
        assert "connected" in p
        assert "allowed_users" in p


def test_get_messenger_platforms_with_router():
    """Test GET /api/messenger/platforms uses router for status."""
    from breadmind.messenger.router import MessageRouter
    router = MessageRouter()
    router.set_allowed_users("slack", ["user1", "user2"])
    app = WebApp(message_handler=lambda m, **kw: "ok", message_router=router)
    client = TestClient(app.app)
    resp = client.get("/api/messenger/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert data["platforms"]["slack"]["allowed_users"] == ["user1", "user2"]


def test_post_messenger_token_saves(monkeypatch):
    """Test POST /api/messenger/slack/token saves tokens."""
    import os
    # Clean up before test
    for k in ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]:
        os.environ.pop(k, None)
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/messenger/slack/token", json={
        "bot_token": "xoxb-test-token-123",
        "app_token": "xapp-test-token-456",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "bot_token" in data["saved"]
    assert "app_token" in data["saved"]
    assert data["platform"] == "slack"
    assert os.environ.get("SLACK_BOT_TOKEN") == "xoxb-test-token-123"
    assert os.environ.get("SLACK_APP_TOKEN") == "xapp-test-token-456"
    # Clean up
    os.environ.pop("SLACK_BOT_TOKEN", None)
    os.environ.pop("SLACK_APP_TOKEN", None)


def test_post_messenger_token_invalid_platform():
    """Test POST /api/messenger/invalid/token returns 400."""
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/messenger/invalid/token", json={"bot_token": "test"})
    assert resp.status_code == 400
    assert "Invalid platform" in resp.json()["error"]


def test_post_messenger_test_no_router():
    """Test POST /api/messenger/slack/test returns 503 when no router."""
    app = WebApp(message_handler=lambda m, **kw: "ok")
    client = TestClient(app.app)
    resp = client.post("/api/messenger/slack/test")
    assert resp.status_code == 503


def test_post_messenger_test_with_router_no_gateway():
    """Test POST /api/messenger/slack/test returns not_connected when no gateway."""
    from breadmind.messenger.router import MessageRouter
    router = MessageRouter()
    app = WebApp(message_handler=lambda m, **kw: "ok", message_router=router)
    client = TestClient(app.app)
    resp = client.post("/api/messenger/slack/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_connected"


def test_post_messenger_test_with_gateway():
    """Test POST /api/messenger/slack/test returns ok when gateway exists."""
    from breadmind.messenger.router import MessageRouter, MessengerGateway

    class FakeGateway(MessengerGateway):
        async def start(self): pass
        async def stop(self): pass
        async def send(self, channel_id, text): pass
        async def ask_approval(self, channel_id, action_name, params): return "id"

    router = MessageRouter()
    router.register_gateway("slack", FakeGateway())
    app = WebApp(message_handler=lambda m, **kw: "ok", message_router=router)
    client = TestClient(app.app)
    resp = client.post("/api/messenger/slack/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_post_messenger_test_invalid_platform():
    """Test POST /api/messenger/invalid/test returns 400."""
    from breadmind.messenger.router import MessageRouter
    router = MessageRouter()
    app = WebApp(message_handler=lambda m, **kw: "ok", message_router=router)
    client = TestClient(app.app)
    resp = client.post("/api/messenger/invalid/test")
    assert resp.status_code == 400
