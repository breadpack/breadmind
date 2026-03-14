import pytest
from breadmind.tools.registry import ToolRegistry, tool, MAX_OUTPUT_SIZE
from breadmind.llm.base import ToolDefinition


@tool(description="Echo the input message back")
async def echo(message: str) -> str:
    """Echo tool for testing."""
    return f"echo: {message}"


@tool(description="Add two numbers")
async def add(a: int, b: int) -> str:
    """Add tool for testing."""
    return f"result: {a + b}"


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


@pytest.mark.asyncio
async def test_registry_filters_unexpected_parameters():
    """Test that unexpected parameters are filtered out and don't cause errors."""
    registry = ToolRegistry()
    registry.register(echo)
    result = await registry.execute("echo", {"message": "hello", "unexpected_param": "value"})
    assert result.success is True
    assert result.output == "echo: hello"


@pytest.mark.asyncio
async def test_registry_type_coercion_string_to_int():
    """Test that string values are coerced to integers when schema expects integer."""
    registry = ToolRegistry()
    registry.register(add)
    result = await registry.execute("add", {"a": "3", "b": "4"})
    assert result.success is True
    assert "7" in result.output


@pytest.mark.asyncio
async def test_registry_type_coercion_invalid():
    """Test that invalid type coercion results in a validation error."""
    registry = ToolRegistry()
    registry.register(add)
    result = await registry.execute("add", {"a": "not_a_number", "b": "4"})
    assert result.success is False
    assert "validation error" in result.output.lower()


@pytest.mark.asyncio
async def test_registry_output_truncation():
    """Test that large output is truncated."""

    @tool(description="Generate large output")
    async def large_output() -> str:
        return "x" * (MAX_OUTPUT_SIZE + 1000)

    registry = ToolRegistry()
    registry.register(large_output)
    result = await registry.execute("large_output", {})
    assert result.success is True
    assert len(result.output) == MAX_OUTPUT_SIZE + len(f"[...truncated, showing first {MAX_OUTPUT_SIZE} chars]")
    assert result.output.endswith(f"[...truncated, showing first {MAX_OUTPUT_SIZE} chars]")


@pytest.mark.asyncio
async def test_registry_output_not_truncated_when_small():
    """Test that small output is not truncated."""
    registry = ToolRegistry()
    registry.register(echo)
    result = await registry.execute("echo", {"message": "small"})
    assert result.success is True
    assert "truncated" not in result.output


@pytest.mark.asyncio
async def test_registry_validation_error_on_bad_type():
    """Test that validation errors return ToolResult with success=False."""
    registry = ToolRegistry()
    registry.register(add)
    # Pass a list which can't be converted to integer
    result = await registry.execute("add", {"a": [1, 2, 3], "b": 4})
    assert result.success is False
    assert "error" in result.output.lower()
