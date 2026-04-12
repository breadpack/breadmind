"""Tests for LSP client code navigation tools."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch


from breadmind.tools.lsp_client import LSPClient


# ── Helper: create a temp Python file ──


def _make_temp_file(content: str) -> str:
    """Write content to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


SAMPLE_CODE = """\
class MyClass:
    def __init__(self):
        self.value = 0

    def get_value(self):
        return self.value

def helper_function(x):
    return x + 1

async def async_worker(data):
    result = helper_function(data)
    return result
"""


# ── Fallback definition tests ──


async def test_fallback_definition_finds_function():
    path = _make_temp_file(SAMPLE_CODE)
    try:
        client = LSPClient(workspace_path="/tmp")
        # Line 11 col 15: "helper_function" usage
        locations = await client.goto_definition(path, 11, 15)
        assert len(locations) > 0
        names = [loc.preview for loc in locations]
        assert any("def helper_function" in p for p in names)
    finally:
        os.unlink(path)


async def test_fallback_definition_finds_class():
    path = _make_temp_file(SAMPLE_CODE)
    try:
        client = LSPClient(workspace_path="/tmp")
        # Search for MyClass definition from line where it's referenced
        # We add a line referencing MyClass
        code_with_ref = SAMPLE_CODE + "\nobj = MyClass()\n"
        with open(path, "w") as f:
            f.write(code_with_ref)

        # The reference is at the last line, col 6
        locations = await client.goto_definition(path, 14, 6)
        assert len(locations) > 0
        names = [loc.preview for loc in locations]
        assert any("class MyClass" in p for p in names)
    finally:
        os.unlink(path)


# ── Fallback references tests ──


async def test_fallback_references_finds_occurrences():
    path = _make_temp_file(SAMPLE_CODE)
    try:
        client = LSPClient(workspace_path="/tmp")
        # Find references to "helper_function" from its definition line (7)
        locations = await client.find_references(path, 7, 4)
        # Should find at least the definition and the usage
        assert len(locations) >= 2
        lines = {loc.line for loc in locations}
        assert 7 in lines   # definition
        assert 11 in lines  # usage
    finally:
        os.unlink(path)


# ── Fallback symbols tests ──


async def test_fallback_symbols_extracts_all():
    path = _make_temp_file(SAMPLE_CODE)
    try:
        client = LSPClient(workspace_path="/tmp")
        symbols = await client.document_symbols(path)

        names = {s.name for s in symbols}
        assert "MyClass" in names
        assert "__init__" in names
        assert "get_value" in names
        assert "helper_function" in names
        assert "async_worker" in names

        # Check kinds
        kinds = {s.name: s.kind for s in symbols}
        assert kinds["MyClass"] == "class"
        assert kinds["helper_function"] == "function"
        assert kinds["async_worker"] == "function"
    finally:
        os.unlink(path)


# ── Utility method tests ──


async def test_extract_word_at_position():
    assert LSPClient._extract_word("def hello_world(x):", 4) == "hello_world"
    assert LSPClient._extract_word("def hello_world(x):", 0) == "def"
    assert LSPClient._extract_word("  x = 42", 2) == "x"
    assert LSPClient._extract_word("", 0) == ""
    assert LSPClient._extract_word("abc", 10) == ""  # out of bounds


async def test_path_to_uri_conversion():
    client = LSPClient(workspace_path="/tmp")

    # Unix-style path
    with patch("os.path.abspath", return_value="/home/user/file.py"):
        uri = client._path_to_uri("/home/user/file.py")
        assert uri == "file:///home/user/file.py"

    # Windows-style path
    with patch("os.path.abspath", return_value="C:/Users/test/file.py"):
        uri = client._path_to_uri("C:\\Users\\test\\file.py")
        assert uri == "file:///C:/Users/test/file.py"


async def test_uri_to_path_conversion():
    client = LSPClient(workspace_path="/tmp")

    # Unix URI
    with patch("os.sep", "/"):
        path = client._uri_to_path("file:///home/user/file.py")
        assert path == "/home/user/file.py"

    # Windows URI
    with patch("os.sep", "\\"):
        path = client._uri_to_path("file:///C:/Users/test/file.py")
        assert path == "C:\\Users\\test\\file.py"

    # Non-file URI passthrough
    assert client._uri_to_path("https://example.com") == "https://example.com"


async def test_parse_locations():
    client = LSPClient(workspace_path="/tmp")

    # Single location (dict)
    result = {
        "uri": "file:///tmp/test.py",
        "range": {
            "start": {"line": 5, "character": 10},
            "end": {"line": 5, "character": 20},
        },
    }
    locations = client._parse_locations(result)
    assert len(locations) == 1
    assert locations[0].line == 5
    assert locations[0].character == 10
    assert locations[0].end_line == 5
    assert locations[0].end_character == 20

    # Multiple locations (list)
    result_list = [result, result]
    locations = client._parse_locations(result_list)
    assert len(locations) == 2

    # None
    assert client._parse_locations(None) == []


async def test_hover_returns_none_when_not_initialized():
    client = LSPClient(workspace_path="/tmp")
    assert not client._initialized
    result = await client.hover("/tmp/test.py", 0, 0)
    assert result is None


async def test_default_server_for_python():
    client = LSPClient(language="python")
    assert client._server_command == "pyright-langserver --stdio"

    client2 = LSPClient(language="go")
    assert client2._server_command == "gopls"

    # Unknown language returns empty string
    client3 = LSPClient(language="cobol")
    assert client3._server_command == ""


async def test_start_failure_graceful():
    """Starting with a non-existent server command should return False gracefully."""
    client = LSPClient(
        language="python",
        server_command="nonexistent-lsp-server-binary --stdio",
        workspace_path="/tmp",
    )

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("No such file"),
    ):
        result = await client.start()

    assert result is False
    assert not client._initialized
