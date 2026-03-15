import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.meta import create_memory_tools


class TestMemoryTools:
    def _make_tools(self):
        episodic = AsyncMock()
        episodic.add_note = AsyncMock(return_value=MagicMock(id=1))
        episodic.search_by_keywords = AsyncMock(return_value=[])
        episodic.delete_note = AsyncMock(return_value=True)
        return create_memory_tools(episodic_memory=episodic), episodic

    @pytest.mark.asyncio
    async def test_memory_save(self):
        tools, episodic = self._make_tools()
        result = await tools["memory_save"](content="User prefers rolling updates", category="preference")
        assert "Remembered" in result
        episodic.add_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_save_invalid_category(self):
        tools, episodic = self._make_tools()
        result = await tools["memory_save"](content="test", category="invalid")
        assert "Remembered" in result
        # Should default to "fact"
        call_args = episodic.add_note.call_args
        assert "memory:fact" in call_args.kwargs.get("tags", []) or "memory:fact" in call_args[1].get("tags", [])

    @pytest.mark.asyncio
    async def test_memory_search_empty(self):
        tools, _ = self._make_tools()
        result = await tools["memory_search"](query="kubernetes")
        assert "No relevant memories" in result

    @pytest.mark.asyncio
    async def test_memory_search_with_results(self):
        tools, episodic = self._make_tools()
        note = MagicMock()
        note.content = "User prefers rolling updates for K8s deployments"
        episodic.search_by_keywords = AsyncMock(return_value=[note])
        result = await tools["memory_search"](query="deployment preference")
        assert "rolling updates" in result

    @pytest.mark.asyncio
    async def test_memory_delete_found(self):
        tools, episodic = self._make_tools()
        note = MagicMock()
        note.id = 42
        note.content = "User prefers dark mode"
        episodic.search_by_keywords = AsyncMock(return_value=[note])
        result = await tools["memory_delete"](content_match="dark mode")
        assert "Deleted 1" in result
        episodic.delete_note.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_memory_delete_not_found(self):
        tools, episodic = self._make_tools()
        episodic.search_by_keywords = AsyncMock(return_value=[])
        result = await tools["memory_delete"](content_match="nonexistent")
        assert "No matching" in result

    @pytest.mark.asyncio
    async def test_memory_not_available(self):
        tools = create_memory_tools(episodic_memory=None)
        result = await tools["memory_save"](content="test")
        assert "not available" in result
        result = await tools["memory_search"](query="test")
        assert "not available" in result
