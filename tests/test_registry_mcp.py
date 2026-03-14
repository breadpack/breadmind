import pytest
from unittest.mock import AsyncMock
from breadmind.tools.registry import ToolRegistry, ToolResult, tool
from breadmind.llm.base import ToolDefinition

@tool(description="Builtin echo")
async def echo(message: str) -> str:
    return f"echo: {message}"

def test_register_mcp_tool():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="myserver__list_items",
        description="List items",
        parameters={"type": "object", "properties": {}},
    )
    registry.register_mcp_tool(defn, server_name="myserver")
    assert registry.has_tool("myserver__list_items")
    assert registry.get_tool_source("myserver__list_items") == "mcp:myserver"

def test_unregister_mcp_tools():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="myserver__tool_a",
        description="Tool A",
        parameters={"type": "object", "properties": {}},
    )
    registry.register_mcp_tool(defn, server_name="myserver")
    assert registry.has_tool("myserver__tool_a")
    registry.unregister_mcp_tools("myserver")
    assert not registry.has_tool("myserver__tool_a")

def test_builtin_tool_source():
    registry = ToolRegistry()
    registry.register(echo)
    assert registry.get_tool_source("echo") == "builtin"

def test_mcp_tools_in_definitions():
    registry = ToolRegistry()
    registry.register(echo)
    defn = ToolDefinition(
        name="srv__do_thing",
        description="Do thing",
        parameters={"type": "object", "properties": {}},
    )
    registry.register_mcp_tool(defn, server_name="srv")
    defs = registry.get_all_definitions()
    names = [d.name for d in defs]
    assert "echo" in names
    assert "srv__do_thing" in names

@pytest.mark.asyncio
async def test_execute_mcp_tool_delegates():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="srv__action",
        description="Action",
        parameters={"type": "object", "properties": {}},
    )
    callback = AsyncMock(return_value=ToolResult(success=True, output="mcp result"))
    registry.register_mcp_tool(defn, server_name="srv", execute_callback=callback)
    result = await registry.execute("srv__action", {"key": "val"})
    assert result.success is True
    assert result.output == "mcp result"
    callback.assert_called_once_with("srv", "action", {"key": "val"})
