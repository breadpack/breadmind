"""Tests for LSP tools (with mocked LSPClient)."""
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.tools.lsp_client import LSPLocation, LSPSymbol


@patch("breadmind.tools.lsp_client.LSPClient")
async def test_goto_definition_returns_locations(mock_cls):
    from breadmind.tools.lsp_tools import lsp_goto_definition

    mock_client = MagicMock()
    mock_client.goto_definition = AsyncMock(return_value=[
        LSPLocation(file_path="/src/main.py", line=10, character=4, preview="def main():"),
    ])
    mock_cls.return_value = mock_client

    result = await lsp_goto_definition(file_path="/src/app.py", line=5, character=10)
    assert "/src/main.py:11:4" in result
    assert "def main():" in result


@patch("breadmind.tools.lsp_client.LSPClient")
async def test_find_references(mock_cls):
    from breadmind.tools.lsp_tools import lsp_find_references

    mock_client = MagicMock()
    mock_client.find_references = AsyncMock(return_value=[
        LSPLocation(file_path="/src/a.py", line=3, character=0, preview="import foo"),
        LSPLocation(file_path="/src/b.py", line=7, character=0, preview="foo.bar()"),
    ])
    mock_cls.return_value = mock_client

    result = await lsp_find_references(file_path="/src/foo.py", line=1, character=0)
    assert "Found 2 references" in result
    assert "/src/a.py:4" in result
    assert "/src/b.py:8" in result


@patch("breadmind.tools.lsp_client.LSPClient")
async def test_document_symbols(mock_cls):
    from breadmind.tools.lsp_tools import lsp_document_symbols

    mock_client = MagicMock()
    mock_client.document_symbols = AsyncMock(return_value=[
        LSPSymbol(name="MyClass", kind="class",
                  location=LSPLocation(file_path="/src/mod.py", line=0, character=0)),
        LSPSymbol(name="do_work", kind="function",
                  location=LSPLocation(file_path="/src/mod.py", line=15, character=0)),
    ])
    mock_cls.return_value = mock_client

    result = await lsp_document_symbols(file_path="/src/mod.py")
    assert "Symbols in /src/mod.py" in result
    assert "[class] MyClass" in result
    assert "[function] do_work" in result
    assert "line 16" in result
