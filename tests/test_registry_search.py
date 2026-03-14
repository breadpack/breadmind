import pytest
from unittest.mock import AsyncMock, patch
from breadmind.tools.registry_search import (
    RegistrySearchEngine, RegistrySearchResult, RegistryConfig,
)

@pytest.fixture
def engine():
    configs = [
        RegistryConfig(name="clawhub", type="clawhub", enabled=True),
        RegistryConfig(name="mcp-registry", type="mcp_registry",
                       url="https://registry.modelcontextprotocol.io", enabled=True),
    ]
    return RegistrySearchEngine(configs)

@pytest.mark.asyncio
async def test_search_returns_results(engine):
    with patch.object(engine, "_search_clawhub", new_callable=AsyncMock) as mock_ch, \
         patch.object(engine, "_search_mcp_registry", new_callable=AsyncMock) as mock_mr:
        mock_ch.return_value = [
            RegistrySearchResult(name="mcp-proxmox", slug="mcp-proxmox",
                                 description="Proxmox MCP server", source="clawhub",
                                 install_command="clawhub install mcp-proxmox")
        ]
        mock_mr.return_value = [
            RegistrySearchResult(name="proxmox-mcp-plus", slug="proxmox-mcp-plus",
                                 description="Another Proxmox MCP", source="mcp_registry",
                                 install_command=None)
        ]
        results = await engine.search("proxmox")
        assert len(results) == 2
        assert results[0].source == "clawhub"

@pytest.mark.asyncio
async def test_search_deduplicates(engine):
    with patch.object(engine, "_search_clawhub", new_callable=AsyncMock) as mock_ch, \
         patch.object(engine, "_search_mcp_registry", new_callable=AsyncMock) as mock_mr:
        mock_ch.return_value = [
            RegistrySearchResult(name="my-tool", slug="my-tool",
                                 description="A tool", source="clawhub", install_command=None)
        ]
        mock_mr.return_value = [
            RegistrySearchResult(name="my-tool", slug="my-tool",
                                 description="A tool", source="mcp_registry", install_command=None)
        ]
        results = await engine.search("tool")
        assert len(results) == 1

@pytest.mark.asyncio
async def test_search_skips_failed_registry(engine):
    with patch.object(engine, "_search_clawhub", new_callable=AsyncMock) as mock_ch, \
         patch.object(engine, "_search_mcp_registry", new_callable=AsyncMock) as mock_mr:
        mock_ch.side_effect = Exception("API down")
        mock_mr.return_value = [
            RegistrySearchResult(name="tool", slug="tool",
                                 description="Works", source="mcp_registry", install_command=None)
        ]
        results = await engine.search("tool")
        assert len(results) == 1

@pytest.mark.asyncio
async def test_disabled_registry_skipped():
    configs = [RegistryConfig(name="clawhub", type="clawhub", enabled=False)]
    engine = RegistrySearchEngine(configs)
    results = await engine.search("anything")
    assert results == []
