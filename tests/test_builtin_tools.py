import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch
from breadmind.tools.builtin import shell_exec, web_search, file_read, file_write

@pytest.mark.asyncio
async def test_shell_exec_local():
    # Use 'echo' which works on both Windows and Unix via shell
    result = await shell_exec(command="echo hello", host="localhost", timeout=5)
    assert "hello" in result

@pytest.mark.asyncio
async def test_file_read_write():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test content")
        path = f.name
    try:
        content = await file_read(path=path)
        assert content == "test content"

        await file_write(path=path, content="new content")
        content2 = await file_read(path=path)
        assert content2 == "new content"
    finally:
        os.unlink(path)

@pytest.mark.asyncio
async def test_file_read_not_found():
    result = await file_read(path="/nonexistent/path/file.txt")
    assert "error" in result.lower() or "not found" in result.lower()

@pytest.mark.asyncio
async def test_web_search():
    with patch("breadmind.tools.builtin._duckduckgo_search", new_callable=AsyncMock) as mock:
        mock.return_value = [
            {"title": "Result 1", "href": "http://example.com", "body": "Description 1"}
        ]
        result = await web_search(query="test query", limit=1)
        assert "Result 1" in result

def test_tools_have_definitions():
    assert hasattr(shell_exec, "_tool_definition")
    assert hasattr(web_search, "_tool_definition")
    assert hasattr(file_read, "_tool_definition")
    assert hasattr(file_write, "_tool_definition")
