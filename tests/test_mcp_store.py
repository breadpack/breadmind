import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from breadmind.mcp.install_assistant import InstallAssistant
from breadmind.mcp.store import MCPStore
from breadmind.llm.base import LLMResponse, LLMMessage, ToolDefinition, TokenUsage
from breadmind.tools.mcp_client import MCPServerInfo
from breadmind.tools.registry_search import RegistrySearchResult
from breadmind.web.app import WebApp


# --- Fixtures ---

@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    return provider


@pytest.fixture
def assistant(mock_provider):
    return InstallAssistant(mock_provider)


@pytest.fixture
def mock_mcp_manager():
    mgr = AsyncMock()
    mgr.list_servers = AsyncMock(return_value=[])
    mgr.start_stdio_server = AsyncMock(return_value=[])
    mgr.stop_server = AsyncMock()
    mgr.call_tool = AsyncMock()
    return mgr


@pytest.fixture
def mock_search_engine():
    engine = AsyncMock()
    engine.search = AsyncMock(return_value=[])
    return engine


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_setting = AsyncMock(return_value=None)
    db.set_setting = AsyncMock()
    db.delete_setting = AsyncMock(return_value=True)
    db.get_all_settings = AsyncMock(return_value={})
    return db


@pytest.fixture
def mock_tool_registry():
    reg = MagicMock()
    reg.get_all_definitions.return_value = []
    reg.get_tool_source.return_value = "unknown"
    reg.register_mcp_tool = MagicMock()
    reg.unregister_mcp_tools = MagicMock()
    return reg


@pytest.fixture
def store(mock_mcp_manager, mock_search_engine, assistant, mock_db, mock_tool_registry):
    return MCPStore(
        mcp_manager=mock_mcp_manager,
        registry_search=mock_search_engine,
        install_assistant=assistant,
        db=mock_db,
        tool_registry=mock_tool_registry,
    )


@pytest.fixture
def store_no_assistant(mock_mcp_manager, mock_search_engine, mock_db, mock_tool_registry):
    return MCPStore(
        mcp_manager=mock_mcp_manager,
        registry_search=mock_search_engine,
        install_assistant=None,
        db=mock_db,
        tool_registry=mock_tool_registry,
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        stop_reason="end_turn",
    )


# --- InstallAssistant Tests ---

class TestInstallAssistant:
    @pytest.mark.asyncio
    async def test_analyze_success(self, assistant, mock_provider):
        analysis = {
            "runtime": "node",
            "command": "npx",
            "args": ["-y", "@mcp/server-github"],
            "required_env": [{"name": "GITHUB_TOKEN", "description": "Token", "secret": True}],
            "optional_env": [],
            "dependencies": ["node>=18"],
            "summary": "GitHub MCP server",
        }
        mock_provider.chat.return_value = _make_llm_response(json.dumps(analysis))

        result = await assistant.analyze({
            "name": "github", "description": "GitHub server",
            "source": "registry", "install_command": "npx -y @mcp/server-github",
        })

        assert result["runtime"] == "node"
        assert result["command"] == "npx"
        assert len(result["required_env"]) == 1
        assert result["required_env"][0]["name"] == "GITHUB_TOKEN"

    @pytest.mark.asyncio
    async def test_analyze_fallback_on_failure(self, assistant, mock_provider):
        mock_provider.chat.side_effect = Exception("LLM unavailable")

        result = await assistant.analyze({
            "name": "test", "description": "Test server",
            "source": "registry", "install_command": "npx -y @mcp/test",
        })

        assert result["runtime"] == "node"
        assert result["command"] == "npx"
        assert result["args"] == ["-y", "@mcp/test"]

    @pytest.mark.asyncio
    async def test_analyze_fallback_python(self, assistant, mock_provider):
        mock_provider.chat.side_effect = Exception("fail")

        result = await assistant.analyze({
            "name": "test", "description": "desc",
            "source": "registry", "install_command": "pip install mcp-test",
        })

        assert result["runtime"] == "python"

    @pytest.mark.asyncio
    async def test_troubleshoot_success(self, assistant, mock_provider):
        fix = {
            "analysis": "npm not found",
            "suggestion": "Install Node.js",
            "auto_fix_available": True,
            "fix_command": "apt install nodejs",
        }
        mock_provider.chat.return_value = _make_llm_response(json.dumps(fix))

        result = await assistant.troubleshoot("test-server", "npx", ["-y", "pkg"], "npm: command not found")

        assert result["auto_fix_available"] is True
        assert "nodejs" in result["fix_command"]

    @pytest.mark.asyncio
    async def test_troubleshoot_llm_failure(self, assistant, mock_provider):
        mock_provider.chat.side_effect = Exception("timeout")

        result = await assistant.troubleshoot("test", "cmd", [], "error")

        assert result["auto_fix_available"] is False
        assert "LLM 분석 실패" in result["analysis"]

    def test_parse_json_plain(self, assistant):
        result = assistant._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_with_markdown_fences(self, assistant):
        text = '```json\n{"key": "value"}\n```'
        result = assistant._parse_json(text)
        assert result == {"key": "value"}

    def test_parse_json_with_fences_no_language(self, assistant):
        text = '```\n{"key": "value"}\n```'
        result = assistant._parse_json(text)
        assert result == {"key": "value"}

    def test_fallback_analyze_unknown(self, assistant):
        result = assistant._fallback_analyze({"install_command": "some-binary run", "description": "desc"})
        assert result["runtime"] == "unknown"
        assert result["command"] == "some-binary"

    def test_fallback_analyze_empty_command(self, assistant):
        result = assistant._fallback_analyze({"install_command": "", "description": "desc"})
        assert result["command"] == ""
        assert result["args"] == []


# --- MCPStore Tests ---

class TestMCPStore:
    @pytest.mark.asyncio
    async def test_search(self, store, mock_search_engine):
        mock_search_engine.search.return_value = [
            RegistrySearchResult(name="github", slug="github-mcp", description="GitHub tools",
                                 source="clawhub", install_command="npx github-mcp"),
            RegistrySearchResult(name="slack", slug="slack-mcp", description="Slack tools",
                                 source="mcp_registry", install_command=None),
        ]

        results = await store.search("git", limit=5)

        assert len(results) == 2
        assert results[0]["name"] == "github"
        assert results[0]["slug"] == "github-mcp"
        assert results[1]["install_command"] is None
        mock_search_engine.search.assert_called_once_with("git", limit=5)

    @pytest.mark.asyncio
    async def test_analyze_server_with_assistant(self, store, mock_provider):
        analysis = {"runtime": "node", "command": "npx", "args": [], "required_env": [],
                     "optional_env": [], "dependencies": [], "summary": "test"}
        mock_provider.chat.return_value = _make_llm_response(json.dumps(analysis))

        result = await store.analyze_server({"name": "test", "install_command": "npx test"})

        assert result["runtime"] == "node"

    @pytest.mark.asyncio
    async def test_analyze_server_without_assistant(self, store_no_assistant):
        result = await store_no_assistant.analyze_server({
            "name": "test", "description": "desc",
            "install_command": "npx -y @mcp/test",
        })

        assert result["runtime"] == "unknown"
        assert result["command"] == "npx"

    @pytest.mark.asyncio
    async def test_install_server_success(self, store, mock_mcp_manager, mock_tool_registry, mock_db):
        definitions = [
            ToolDefinition(name="test__tool1", description="Tool 1", parameters={"type": "object", "properties": {}}),
            ToolDefinition(name="test__tool2", description="Tool 2", parameters={"type": "object", "properties": {}}),
        ]
        mock_mcp_manager.start_stdio_server.return_value = definitions

        with patch("breadmind.mcp.store.MCPStore._save_server_to_db", new_callable=AsyncMock):
            result = await store.install_server(
                name="test", slug="test-slug", command="npx",
                args=["-y", "test"], env={"KEY": "val"},
            )

        assert result["status"] == "ok"
        assert result["tool_count"] == 2
        assert "test__tool1" in result["tools"]
        mock_mcp_manager.start_stdio_server.assert_called_once()
        assert mock_tool_registry.register_mcp_tool.call_count == 2

    @pytest.mark.asyncio
    async def test_install_server_failure_with_troubleshoot(self, store, mock_mcp_manager, mock_provider):
        mock_mcp_manager.start_stdio_server.side_effect = Exception("Process failed to start")
        fix = {"analysis": "error", "suggestion": "fix it",
               "auto_fix_available": False, "fix_command": ""}
        mock_provider.chat.return_value = _make_llm_response(json.dumps(fix))

        result = await store.install_server(
            name="broken", slug="broken-slug", command="bad-cmd", args=[],
        )

        assert result["status"] == "error"
        assert "Process failed" in result["error"]
        assert "troubleshoot" in result

    @pytest.mark.asyncio
    async def test_stop_server(self, store, mock_mcp_manager, mock_tool_registry, mock_db):
        result = await store.stop_server("test")

        assert result["status"] == "ok"
        mock_mcp_manager.stop_server.assert_called_once_with("test")
        mock_tool_registry.unregister_mcp_tools.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_stop_server_error(self, store, mock_mcp_manager):
        mock_mcp_manager.stop_server.side_effect = Exception("not running")

        result = await store.stop_server("test")

        assert result["status"] == "error"
        assert "not running" in result["error"]

    @pytest.mark.asyncio
    async def test_remove_server(self, store, mock_mcp_manager, mock_tool_registry, mock_db):
        result = await store.remove_server("test")

        assert result["status"] == "ok"
        mock_mcp_manager.stop_server.assert_called_once_with("test")
        mock_tool_registry.unregister_mcp_tools.assert_called_once_with("test")
        mock_db.delete_setting.assert_called_once_with("mcp_server:test")

    @pytest.mark.asyncio
    async def test_remove_server_stop_fails_gracefully(self, store, mock_mcp_manager, mock_db):
        mock_mcp_manager.stop_server.side_effect = Exception("already stopped")

        result = await store.remove_server("test")

        assert result["status"] == "ok"  # Should still succeed
        mock_db.delete_setting.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_installed_running_servers(self, store, mock_mcp_manager):
        mock_mcp_manager.list_servers.return_value = [
            MCPServerInfo(name="github", transport="stdio", status="running",
                         tools=["list_repos"], source="clawhub"),
        ]

        servers = await store.list_installed()

        assert len(servers) == 1
        assert servers[0]["name"] == "github"
        assert servers[0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_installed_includes_db_stopped(self, store, mock_mcp_manager, mock_db):
        mock_mcp_manager.list_servers.return_value = [
            MCPServerInfo(name="github", transport="stdio", status="running",
                         tools=["list_repos"], source="clawhub"),
        ]
        mock_db.get_all_settings.return_value = {
            "mcp_server:slack": {
                "config": {"source": "registry"},
                "status": "stopped",
            },
        }

        servers = await store.list_installed()

        assert len(servers) == 2
        names = {s["name"] for s in servers}
        assert "github" in names
        assert "slack" in names

    @pytest.mark.asyncio
    async def test_list_installed_no_duplicate(self, store, mock_mcp_manager, mock_db):
        """Running server in MCP manager should not be duplicated from DB."""
        mock_mcp_manager.list_servers.return_value = [
            MCPServerInfo(name="github", transport="stdio", status="running",
                         tools=["list_repos"], source="clawhub"),
        ]
        mock_db.get_all_settings.return_value = {
            "mcp_server:github": {
                "config": {"source": "clawhub"},
                "status": "running",
            },
        }

        servers = await store.list_installed()

        assert len(servers) == 1

    @pytest.mark.asyncio
    async def test_start_server_no_db(self, mock_mcp_manager, mock_search_engine):
        store = MCPStore(mcp_manager=mock_mcp_manager, registry_search=mock_search_engine, db=None)

        result = await store.start_server("test")

        assert result["status"] == "error"
        assert "No database" in result["error"]

    @pytest.mark.asyncio
    async def test_start_server_not_found(self, store, mock_db):
        mock_db.get_setting.return_value = None

        result = await store.start_server("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_server_tools(self, store, mock_tool_registry):
        defs = [
            ToolDefinition(name="srv__tool1", description="T1", parameters={}),
            ToolDefinition(name="other__tool2", description="T2", parameters={}),
        ]
        mock_tool_registry.get_all_definitions.return_value = defs
        mock_tool_registry.get_tool_source.side_effect = lambda n: "mcp:srv" if n.startswith("srv") else "mcp:other"

        tools = await store.get_server_tools("srv")

        assert len(tools) == 1
        assert tools[0]["name"] == "srv__tool1"


# --- Web API Endpoint Tests ---

class TestMCPStoreWebEndpoints:
    @pytest.fixture
    def mcp_store(self, mock_mcp_manager, mock_search_engine):
        return MCPStore(
            mcp_manager=mock_mcp_manager,
            registry_search=mock_search_engine,
        )

    @pytest.fixture
    def web_app(self, mcp_store):
        return WebApp(
            message_handler=AsyncMock(return_value="ok"),
            mcp_store=mcp_store,
        )

    @pytest.fixture
    def client(self, web_app):
        return TestClient(web_app.app)

    def test_search_empty(self, client, mock_search_engine):
        mock_search_engine.search.return_value = []
        resp = client.get("/api/mcp/search?q=test")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_search_results(self, client, mock_search_engine):
        mock_search_engine.search.return_value = [
            RegistrySearchResult(name="github", slug="github-mcp", description="GitHub",
                                 source="clawhub", install_command="npx github"),
        ]
        resp = client.get("/api/mcp/search?q=github&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "github"

    def test_search_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.get("/api/mcp/search?q=test")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_install_analyze(self, client, mock_search_engine):
        """Test analyze endpoint without assistant (fallback path)."""
        resp = client.post("/api/mcp/install/analyze", json={
            "name": "test", "description": "desc",
            "install_command": "npx -y @mcp/test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "analysis" in data
        assert data["analysis"]["command"] == "npx"

    def test_install_analyze_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.post("/api/mcp/install/analyze", json={"name": "test"})
        assert resp.status_code == 503

    def test_install_execute_success(self, client, mock_mcp_manager):
        mock_mcp_manager.start_stdio_server.return_value = [
            ToolDefinition(name="test__t1", description="T", parameters={}),
        ]
        resp = client.post("/api/mcp/install/execute", json={
            "name": "test", "slug": "test-slug",
            "command": "npx", "args": ["-y", "test"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["tool_count"] == 1

    def test_install_execute_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.post("/api/mcp/install/execute", json={"name": "test"})
        assert resp.status_code == 503

    def test_installed_list(self, client, mock_mcp_manager):
        mock_mcp_manager.list_servers.return_value = [
            MCPServerInfo(name="gh", transport="stdio", status="running",
                         tools=["t1"], source="clawhub"),
        ]
        resp = client.get("/api/mcp/installed")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "gh"

    def test_installed_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.get("/api/mcp/installed")
        assert resp.status_code == 200
        assert resp.json()["servers"] == []

    def test_server_start_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.post("/api/mcp/servers/test/start")
        assert resp.status_code == 503

    def test_server_stop(self, client, mock_mcp_manager):
        resp = client.post("/api/mcp/servers/test/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        mock_mcp_manager.stop_server.assert_called_once_with("test")

    def test_server_stop_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.post("/api/mcp/servers/test/stop")
        assert resp.status_code == 503

    def test_server_remove(self, client, mock_mcp_manager):
        resp = client.delete("/api/mcp/servers/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_server_remove_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.delete("/api/mcp/servers/test")
        assert resp.status_code == 503

    def test_server_tools(self, client):
        resp = client.get("/api/mcp/servers/test/tools")
        assert resp.status_code == 200
        assert resp.json()["tools"] == []

    def test_server_tools_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.get("/api/mcp/servers/test/tools")
        assert resp.status_code == 200
        assert resp.json()["tools"] == []

    def test_troubleshoot_no_store(self):
        app = WebApp(message_handler=AsyncMock(return_value="ok"))
        client = TestClient(app.app)
        resp = client.post("/api/mcp/install/troubleshoot", json={
            "server_name": "test", "error_log": "fail",
        })
        assert resp.status_code == 503

    def test_troubleshoot_no_assistant(self, client):
        """Store exists but no assistant configured."""
        resp = client.post("/api/mcp/install/troubleshoot", json={
            "server_name": "test", "command": "npx",
            "args": [], "error_log": "fail",
        })
        assert resp.status_code == 503
        assert "LLM not available" in resp.json()["error"]
