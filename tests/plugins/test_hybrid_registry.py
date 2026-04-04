import pytest
from breadmind.core.protocols import ToolDefinition, ToolFilter
from breadmind.plugins.v2_builtin.tools.registry import HybridToolRegistry

@pytest.fixture
def registry():
    r = HybridToolRegistry()
    r.register(ToolDefinition(name="shell_exec", description="Execute shell", parameters={}))
    r.register(ToolDefinition(name="file_read", description="Read file", parameters={}))
    r.register(ToolDefinition(name="k8s_pods_list", description="List K8s pods", parameters={}))
    r.register(ToolDefinition(name="k8s_pods_get", description="Get K8s pod", parameters={}))
    r.register(ToolDefinition(name="web_search", description="Web search", parameters={}))
    return r

def test_get_all_schemas(registry):
    schemas = registry.get_schemas()
    assert len(schemas) == 5
    assert all(s.deferred is False for s in schemas)

def test_get_schemas_deferred(registry):
    f = ToolFilter(use_deferred=True, always_include=["shell_exec", "file_read"])
    schemas = registry.get_schemas(f)
    full = [s for s in schemas if not s.deferred]
    deferred = [s for s in schemas if s.deferred]
    assert len(full) == 2
    assert len(deferred) == 3

def test_get_schemas_intent_filter(registry):
    f = ToolFilter(intent="k8s", keywords=["pod", "kubernetes"], max_tools=3)
    schemas = registry.get_schemas(f)
    names = [s.name for s in schemas]
    assert "k8s_pods_list" in names
    assert "k8s_pods_get" in names

def test_resolve_deferred(registry):
    resolved = registry.resolve_deferred(["k8s_pods_list", "web_search"])
    assert len(resolved) == 2
    assert all(s.definition is not None for s in resolved)

def test_get_deferred_tools(registry):
    assert len(registry.get_deferred_tools()) == 5

def test_unregister(registry):
    registry.unregister("web_search")
    assert len(registry.get_schemas()) == 4

def test_unregister_nonexistent(registry):
    registry.unregister("nonexistent")  # should not raise
