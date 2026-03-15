import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.meta import create_meta_tools
from breadmind.tools.mcp_client import MCPClientManager, MCPServerInfo
from breadmind.tools.registry_search import (
    RegistrySearchEngine, RegistrySearchResult, RegistryConfig,
)

@pytest.fixture
def meta_tools():
    manager = MCPClientManager()
    engine = RegistrySearchEngine([])
    tools = create_meta_tools(manager, engine)
    return tools, manager, engine

def test_create_meta_tools_returns_dict(meta_tools):
    tools, _, _ = meta_tools
    assert "mcp_search" in tools
    assert "mcp_install" in tools
    assert "mcp_uninstall" in tools
    assert "mcp_list" in tools
    assert "mcp_recommend" in tools
    assert "mcp_start" in tools
    assert "mcp_stop" in tools
    for func in tools.values():
        assert hasattr(func, "_tool_definition")

@pytest.mark.asyncio
async def test_mcp_search(meta_tools):
    tools, _, engine = meta_tools
    engine.search = AsyncMock(return_value=[
        RegistrySearchResult(
            name="test-mcp", slug="test-mcp",
            description="A test MCP server", source="clawhub",
            install_command="clawhub install test-mcp",
        )
    ])
    result = await tools["mcp_search"](query="test")
    assert "test-mcp" in result

@pytest.mark.asyncio
async def test_mcp_list_empty(meta_tools):
    tools, manager, _ = meta_tools
    result = await tools["mcp_list"]()
    assert "No MCP servers" in result

@pytest.mark.asyncio
async def test_mcp_list_with_servers(meta_tools):
    tools, manager, _ = meta_tools
    manager._servers["my-server"] = MCPServerInfo(
        name="my-server", transport="stdio", status="running",
        tools=["tool_a"], source="config",
    )
    result = await tools["mcp_list"]()
    assert "my-server" in result
    assert "running" in result

@pytest.mark.asyncio
async def test_mcp_recommend(meta_tools):
    tools, _, engine = meta_tools
    engine.search = AsyncMock(return_value=[
        RegistrySearchResult(
            name="recommended-tool", slug="recommended-tool",
            description="A recommended tool", source="clawhub",
            install_command="clawhub install recommended-tool",
        )
    ])
    result = await tools["mcp_recommend"](query="kubernetes")
    assert "recommended-tool" in result
    assert "install" in result.lower()

@pytest.mark.asyncio
async def test_mcp_stop(meta_tools):
    tools, manager, _ = meta_tools
    manager._servers["srv"] = MCPServerInfo(
        name="srv", transport="stdio", status="running", tools=[], source="config"
    )
    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()
    manager._processes["srv"] = mock_proc
    result = await tools["mcp_stop"](name="srv")
    assert "Stopped" in result

@pytest.mark.asyncio
async def test_skill_manage_list():
    from breadmind.core.skill_store import SkillStore
    from breadmind.tools.meta import create_expansion_tools
    skill_store = SkillStore()
    await skill_store.add_skill("s1", "desc", "prompt", [], ["kw"], "manual")
    tools = create_expansion_tools(skill_store=skill_store, tracker=None)
    result = await tools["skill_manage"](action="list")
    assert "s1" in result

@pytest.mark.asyncio
async def test_skill_manage_add():
    from breadmind.core.skill_store import SkillStore
    from breadmind.tools.meta import create_expansion_tools
    skill_store = SkillStore()
    tools = create_expansion_tools(skill_store=skill_store, tracker=None)
    result = await tools["skill_manage"](action="add", name="new_skill",
        description="A new skill", prompt_template="Do things", trigger_keywords="kw1,kw2")
    assert "new_skill" in result
    assert await skill_store.get_skill("new_skill") is not None

@pytest.mark.asyncio
async def test_performance_report():
    from breadmind.core.performance import PerformanceTracker
    from breadmind.tools.meta import create_expansion_tools
    tracker = PerformanceTracker()
    await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
    tools = create_expansion_tools(skill_store=None, tracker=tracker)
    result = await tools["performance_report"]()
    assert "role_a" in result

@pytest.mark.asyncio
async def test_performance_report_specific_role():
    from breadmind.core.performance import PerformanceTracker
    from breadmind.tools.meta import create_expansion_tools
    tracker = PerformanceTracker()
    await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
    tools = create_expansion_tools(skill_store=None, tracker=tracker)
    result = await tools["performance_report"](role="role_a")
    assert "role_a" in result
    assert "100" in result or "1" in result
