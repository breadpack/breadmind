"""Tests for deferred tool schema loading."""

from breadmind.tools.deferred_loader import DeferredToolLoader
from breadmind.tools.registry import ToolRegistry, tool


@tool("A test tool")
def sample_tool_a(name: str):
    return f"hello {name}"


@tool("Another test tool")
def sample_tool_b(count: int):
    return count * 2


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(sample_tool_a)
    reg.register(sample_tool_b)
    return reg


def test_get_deferred_list_returns_names_only():
    loader = DeferredToolLoader(_make_registry())
    entries = loader.get_deferred_list()
    assert len(entries) == 2
    names = {e.name for e in entries}
    assert "sample_tool_a" in names
    assert "sample_tool_b" in names
    for entry in entries:
        assert entry.source == "builtin"
        assert entry.description


def test_get_full_schemas_marks_as_loaded():
    loader = DeferredToolLoader(_make_registry())
    schemas = loader.get_full_schemas(["sample_tool_a"])
    assert len(schemas) == 1
    assert schemas[0].name == "sample_tool_a"
    assert "sample_tool_a" in loader._loaded_schemas
    assert "sample_tool_b" not in loader._loaded_schemas


def test_build_deferred_context_excludes_loaded():
    loader = DeferredToolLoader(_make_registry())
    # Before loading, both should appear
    context = loader.build_deferred_context()
    assert "sample_tool_a" in context
    assert "sample_tool_b" in context

    # After loading one, it should be excluded
    loader.get_full_schemas(["sample_tool_a"])
    context = loader.build_deferred_context()
    assert "sample_tool_a" not in context
    assert "sample_tool_b" in context


def test_context_savings_ratio():
    loader = DeferredToolLoader(_make_registry())
    # Nothing loaded -> 100% savings
    assert loader.context_savings_ratio == 1.0

    # Load one tool
    loader.get_full_schemas(["sample_tool_a"])
    ratio = loader.context_savings_ratio
    assert 0.0 < ratio < 1.0

    # Load all
    loader.get_full_schemas(["sample_tool_b"])
    assert loader.context_savings_ratio == 0.0


def test_reset_clears_loaded():
    loader = DeferredToolLoader(_make_registry())
    loader.get_full_schemas(["sample_tool_a", "sample_tool_b"])
    assert len(loader._loaded_schemas) == 2
    loader.reset()
    assert len(loader._loaded_schemas) == 0


def test_get_active_schemas():
    loader = DeferredToolLoader(_make_registry())
    assert loader.get_active_schemas() == []

    loader.get_full_schemas(["sample_tool_a"])
    active = loader.get_active_schemas()
    assert len(active) == 1
    assert active[0].name == "sample_tool_a"
