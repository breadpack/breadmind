import pytest
import time
import asyncio
from breadmind.tools.registry import ToolRegistry, ToolResultCache, ToolResult, tool, MAX_OUTPUT_SIZE
from breadmind.tools.metrics import MetricsCollector, ToolMetrics
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
async def test_execute_unknown_tool_sets_not_found():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent_tool", {})
    assert result.success is False
    assert result.not_found is True
    assert "nonexistent_tool" in result.output


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


# --- ToolResultCache tests ---

def test_cache_get_set():
    cache = ToolResultCache(ttl_seconds=300, max_size=100)
    result = ToolResult(success=True, output="cached value")
    cache.set("my_tool", {"q": "test"}, result)
    cached = cache.get("my_tool", {"q": "test"})
    assert cached is not None
    assert cached.output == "cached value"


def test_cache_miss():
    cache = ToolResultCache()
    assert cache.get("missing_tool", {"q": "test"}) is None


def test_cache_expiry():
    cache = ToolResultCache(ttl_seconds=0)  # immediate expiry
    result = ToolResult(success=True, output="expired")
    cache.set("tool", {"a": 1}, result)
    # Since ttl=0, the entry should already be expired
    # (monotonic time will have advanced)
    time.sleep(0.01)
    assert cache.get("tool", {"a": 1}) is None


def test_cache_max_size_eviction():
    cache = ToolResultCache(ttl_seconds=300, max_size=2)
    cache.set("t1", {"a": 1}, ToolResult(success=True, output="v1"))
    cache.set("t2", {"a": 2}, ToolResult(success=True, output="v2"))
    cache.set("t3", {"a": 3}, ToolResult(success=True, output="v3"))
    # One of the first two should have been evicted
    assert len(cache._cache) == 2
    # t3 should be present
    assert cache.get("t3", {"a": 3}) is not None


def test_cache_different_arguments_different_keys():
    cache = ToolResultCache()
    r1 = ToolResult(success=True, output="result1")
    r2 = ToolResult(success=True, output="result2")
    cache.set("tool", {"q": "a"}, r1)
    cache.set("tool", {"q": "b"}, r2)
    assert cache.get("tool", {"q": "a"}).output == "result1"
    assert cache.get("tool", {"q": "b"}).output == "result2"


# --- Cacheable vs non-cacheable tools tests ---

@pytest.mark.asyncio
async def test_cacheable_tool_uses_cache():
    cache = ToolResultCache(ttl_seconds=300)
    registry = ToolRegistry(cache=cache, cacheable_tools={"echo"})
    registry.register(echo)

    # First call populates cache
    r1 = await registry.execute("echo", {"message": "hi"})
    assert r1.success is True

    # Second call should return cached result
    r2 = await registry.execute("echo", {"message": "hi"})
    assert r2.success is True
    assert r2.output == r1.output


@pytest.mark.asyncio
async def test_non_cacheable_tool_does_not_cache():
    cache = ToolResultCache(ttl_seconds=300)
    # echo is NOT in cacheable_tools
    registry = ToolRegistry(cache=cache, cacheable_tools=set())
    registry.register(echo)

    await registry.execute("echo", {"message": "hi"})
    # Cache should be empty since tool is not cacheable
    assert cache.get("echo", {"message": "hi"}) is None


@pytest.mark.asyncio
async def test_registry_without_cache():
    """Registry works fine when cache is None."""
    registry = ToolRegistry(cache=None)
    registry.register(echo)
    result = await registry.execute("echo", {"message": "test"})
    assert result.success is True


# --- MetricsCollector tests ---

@pytest.mark.asyncio
async def test_metrics_record_and_get():
    collector = MetricsCollector()
    await collector.record("tool_a", success=True, duration_ms=100.0)
    await collector.record("tool_a", success=False, duration_ms=50.0)

    metrics = collector.get_metrics("tool_a")
    assert metrics["total_calls"] == 2
    assert metrics["success_count"] == 1
    assert metrics["error_count"] == 1
    assert metrics["total_duration_ms"] == 150.0
    assert metrics["avg_duration_ms"] == 75.0
    assert metrics["last_called"] is not None


@pytest.mark.asyncio
async def test_metrics_record_timeout():
    collector = MetricsCollector()
    await collector.record("tool_b", success=False, duration_ms=30000.0, timed_out=True)

    metrics = collector.get_metrics("tool_b")
    assert metrics["timeout_count"] == 1
    assert metrics["error_count"] == 1


@pytest.mark.asyncio
async def test_metrics_get_all():
    collector = MetricsCollector()
    await collector.record("tool_a", success=True, duration_ms=10.0)
    await collector.record("tool_b", success=True, duration_ms=20.0)

    all_metrics = collector.get_metrics()
    assert "tool_a" in all_metrics
    assert "tool_b" in all_metrics


def test_metrics_get_unknown_tool():
    collector = MetricsCollector()
    assert collector.get_metrics("unknown") == {}


@pytest.mark.asyncio
async def test_metrics_get_summary():
    collector = MetricsCollector()
    await collector.record("tool_a", success=True, duration_ms=100.0)
    await collector.record("tool_a", success=True, duration_ms=200.0)
    await collector.record("tool_b", success=False, duration_ms=50.0)

    summary = collector.get_summary()
    assert summary["total_calls"] == 3
    assert summary["avg_latency_ms"] == pytest.approx(350.0 / 3)
    assert summary["error_rate"] == pytest.approx(1 / 3)
    assert len(summary["most_used_tools"]) == 2
    # tool_a should be first (most used)
    assert summary["most_used_tools"][0]["name"] == "tool_a"
    assert summary["most_used_tools"][0]["calls"] == 2


def test_metrics_get_summary_empty():
    collector = MetricsCollector()
    summary = collector.get_summary()
    assert summary["total_calls"] == 0
    assert summary["avg_latency_ms"] == 0
    assert summary["error_rate"] == 0
    assert summary["most_used_tools"] == []


@pytest.mark.asyncio
async def test_metrics_reset():
    collector = MetricsCollector()
    await collector.record("tool_a", success=True, duration_ms=10.0)
    collector.reset()
    assert collector.get_metrics("tool_a") == {}
    assert collector.get_summary()["total_calls"] == 0
