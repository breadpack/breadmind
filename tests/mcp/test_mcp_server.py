"""Tests for MCP Server mode (JSON-RPC 2.0 over stdio)."""

import pytest

from breadmind.mcp.server import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MCPServer,
    MCPServerConfig,
    MCPToolDefinition,
)


@pytest.fixture
def server():
    return MCPServer()


@pytest.fixture
def configured_server():
    config = MCPServerConfig(name="test-server", version="0.1.0")
    srv = MCPServer(config)
    srv.register_tool(
        name="echo",
        description="Echoes input",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda text="": text,
    )
    return srv


def _rpc(method, params=None, id=1):
    msg = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return msg


async def test_initialize_sets_initialized(server: MCPServer):
    assert not server.initialized
    resp = await server.handle_message(_rpc("initialize", {}))
    assert resp is not None
    assert resp["result"]["serverInfo"]["name"] == "breadmind"
    assert server.initialized


async def test_tools_list_before_init_returns_error(configured_server: MCPServer):
    resp = await configured_server.handle_message(_rpc("tools/list"))
    assert "error" in resp
    assert resp["error"]["code"] == INVALID_REQUEST


async def test_tools_list_after_init(configured_server: MCPServer):
    await configured_server.handle_message(_rpc("initialize", {}))
    resp = await configured_server.handle_message(_rpc("tools/list", id=2))
    tools = resp["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"
    assert tools[0]["description"] == "Echoes input"


async def test_tools_call_sync_handler(configured_server: MCPServer):
    await configured_server.handle_message(_rpc("initialize", {}))
    resp = await configured_server.handle_message(
        _rpc("tools/call", {"name": "echo", "arguments": {"text": "hello"}}, id=3)
    )
    assert resp["result"]["isError"] is False
    assert resp["result"]["content"][0]["text"] == "hello"


async def test_tools_call_async_handler():
    srv = MCPServer()
    await srv.handle_message(_rpc("initialize", {}))

    async def async_add(a: int = 0, b: int = 0):
        return {"sum": a + b}

    srv.register_tool("add", "Add numbers", {}, async_add)
    resp = await srv.handle_message(
        _rpc("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}}, id=4)
    )
    assert resp["result"]["isError"] is False
    assert '"sum": 5' in resp["result"]["content"][0]["text"]


async def test_tools_call_unknown_tool(configured_server: MCPServer):
    await configured_server.handle_message(_rpc("initialize", {}))
    resp = await configured_server.handle_message(
        _rpc("tools/call", {"name": "nonexistent"}, id=5)
    )
    assert "error" in resp
    assert resp["error"]["code"] == METHOD_NOT_FOUND


async def test_tools_call_missing_name(configured_server: MCPServer):
    await configured_server.handle_message(_rpc("initialize", {}))
    resp = await configured_server.handle_message(
        _rpc("tools/call", {}, id=6)
    )
    assert "error" in resp
    assert resp["error"]["code"] == INVALID_PARAMS


async def test_tools_call_handler_exception():
    srv = MCPServer()
    await srv.handle_message(_rpc("initialize", {}))

    def bad_handler():
        raise ValueError("boom")

    srv.register_tool("bad", "Fails", {}, bad_handler)
    resp = await srv.handle_message(
        _rpc("tools/call", {"name": "bad"}, id=7)
    )
    assert resp["result"]["isError"] is True
    assert "boom" in resp["result"]["content"][0]["text"]


async def test_unknown_method_returns_error(server: MCPServer):
    await server.handle_message(_rpc("initialize", {}))
    resp = await server.handle_message(_rpc("unknown/method", id=8))
    assert "error" in resp
    assert resp["error"]["code"] == METHOD_NOT_FOUND


async def test_notification_returns_none(server: MCPServer):
    msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    resp = await server.handle_message(msg)
    assert resp is None


async def test_invalid_jsonrpc_version(server: MCPServer):
    msg = {"jsonrpc": "1.0", "method": "initialize", "id": 1}
    resp = await server.handle_message(msg)
    assert "error" in resp
    assert resp["error"]["code"] == INVALID_REQUEST


async def test_tool_count_and_register(server: MCPServer):
    assert server.tool_count == 0
    server.register_tool("t1", "test", {}, lambda: None)
    assert server.tool_count == 1
    server.register_tool("t2", "test2", {}, lambda: None)
    assert server.tool_count == 2


async def test_custom_config():
    config = MCPServerConfig(name="custom", version="2.0.0")
    srv = MCPServer(config)
    resp = await srv.handle_message(_rpc("initialize", {}))
    assert resp["result"]["serverInfo"]["name"] == "custom"
    assert resp["result"]["serverInfo"]["version"] == "2.0.0"
