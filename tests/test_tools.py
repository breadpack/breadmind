import pytest
from breadmind.tools.registry import ToolRegistry, tool
from breadmind.llm.base import ToolDefinition

@tool(description="Echo the input message back")
async def echo(message: str) -> str:
    """Echo tool for testing."""
    return f"echo: {message}"

def test_tool_decorator_creates_definition():
    assert hasattr(echo, "_tool_definition")
    defn = echo._tool_definition
    assert defn.name == "echo"
    assert "message" in defn.parameters.get("properties", {})

def test_registry_register_and_list():
    registry = ToolRegistry()
    registry.register(echo)
    tools = registry.get_all_definitions()
    assert len(tools) == 1
    assert tools[0].name == "echo"

@pytest.mark.asyncio
async def test_registry_execute():
    registry = ToolRegistry()
    registry.register(echo)
    result = await registry.execute("echo", {"message": "hello"})
    assert result.success is True
    assert result.output == "echo: hello"

@pytest.mark.asyncio
async def test_registry_execute_unknown_tool():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent", {})
    assert result.success is False
    assert "not found" in result.output.lower()
