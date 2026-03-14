import pytest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from breadmind.tools.builtin import (
    shell_exec, web_search, file_read, file_write,
    _is_dangerous_command, _validate_path,
    DANGEROUS_PATTERNS, BASE_DIRECTORY,
)
import breadmind.tools.builtin as builtin_module


@pytest.mark.asyncio
async def test_shell_exec_local():
    if sys.platform == "win32":
        result = await shell_exec(command="cmd /c echo hello", host="localhost", timeout=5)
    else:
        result = await shell_exec(command="echo hello", host="localhost", timeout=5)
    assert "hello" in result


@pytest.mark.asyncio
async def test_shell_exec_blocks_dangerous_rm_rf():
    result = await shell_exec(command="rm -rf /", host="localhost", timeout=5)
    assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_shell_exec_blocks_dangerous_mkfs():
    result = await shell_exec(command="mkfs.ext4 /dev/sda", host="localhost", timeout=5)
    assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_shell_exec_blocks_dangerous_dd():
    result = await shell_exec(command="dd if=/dev/zero of=/dev/sda", host="localhost", timeout=5)
    assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_shell_exec_blocks_fork_bomb():
    result = await shell_exec(command=":(){:|:&};:", host="localhost", timeout=5)
    assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_shell_exec_blocks_chmod_777():
    result = await shell_exec(command="chmod -R 777 /", host="localhost", timeout=5)
    assert "blocked" in result.lower()


def test_is_dangerous_command():
    assert _is_dangerous_command("rm -rf /") is True
    assert _is_dangerous_command("mkfs.ext4 /dev/sda") is True
    assert _is_dangerous_command("dd if=/dev/zero of=/dev/sda") is True
    assert _is_dangerous_command("echo hello") is False


@pytest.mark.asyncio
async def test_shell_exec_shlex_split():
    """Test that shlex splitting works correctly with quoted arguments."""
    if sys.platform == "win32":
        # On Windows, test with cmd /c
        result = await shell_exec(command='cmd /c echo "hello world"', host="localhost", timeout=5)
        assert "hello" in result
    else:
        result = await shell_exec(command='echo "hello world"', host="localhost", timeout=5)
        assert "hello world" in result


@pytest.mark.asyncio
async def test_shell_exec_ssh_host_validation():
    """Test that SSH to non-allowed hosts is blocked."""
    # Set allowed hosts to a specific list
    original = builtin_module.ALLOWED_SSH_HOSTS
    try:
        builtin_module.ALLOWED_SSH_HOSTS = ["trusted.example.com"]
        result = await shell_exec(command="echo hi", host="evil.example.com", timeout=5)
        assert "not allowed" in result.lower()
    finally:
        builtin_module.ALLOWED_SSH_HOSTS = original


@pytest.mark.asyncio
async def test_file_read_write():
    # Create temp file inside BASE_DIRECTORY so path validation passes
    path = os.path.join(BASE_DIRECTORY, "_test_rw_temp.txt")
    try:
        with open(path, "w") as f:
            f.write("test content")

        content = await file_read(path=path)
        assert content == "test content"

        await file_write(path=path, content="new content")
        content2 = await file_read(path=path)
        assert content2 == "new content"
    finally:
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_file_read_not_found():
    # Use a path inside BASE_DIRECTORY so it passes traversal check
    result = await file_read(path=os.path.join(BASE_DIRECTORY, "nonexistent_file_xyz.txt"))
    assert "error" in result.lower() or "not found" in result.lower()


@pytest.mark.asyncio
async def test_file_read_path_traversal_blocked():
    """Test that reading files outside base directory is blocked."""
    original_base = builtin_module.BASE_DIRECTORY
    try:
        builtin_module.BASE_DIRECTORY = tempfile.mkdtemp()
        # Try to traverse outside the base directory
        if sys.platform == "win32":
            result = await file_read(path="C:\\Windows\\System32\\drivers\\etc\\hosts")
        else:
            result = await file_read(path="/etc/passwd")
        assert "error" in result.lower()
        assert "traversal" in result.lower() or "outside" in result.lower()
    finally:
        builtin_module.BASE_DIRECTORY = original_base


@pytest.mark.asyncio
async def test_file_write_path_traversal_blocked():
    """Test that writing files outside base directory is blocked."""
    original_base = builtin_module.BASE_DIRECTORY
    try:
        builtin_module.BASE_DIRECTORY = tempfile.mkdtemp()
        if sys.platform == "win32":
            result = await file_write(path="C:\\temp\\evil.txt", content="evil")
        else:
            result = await file_write(path="/tmp/evil.txt", content="evil")
        assert "error" in result.lower()
        assert "traversal" in result.lower() or "outside" in result.lower()
    finally:
        builtin_module.BASE_DIRECTORY = original_base


@pytest.mark.asyncio
async def test_file_read_sensitive_file_blocked():
    """Test that reading sensitive files is blocked."""
    original_base = builtin_module.BASE_DIRECTORY
    try:
        base = tempfile.mkdtemp()
        builtin_module.BASE_DIRECTORY = base
        # Create a .env file inside base
        env_path = os.path.join(base, ".env")
        with open(env_path, "w") as f:
            f.write("SECRET=value")
        result = await file_read(path=env_path)
        assert "error" in result.lower()
        assert "sensitive" in result.lower() or "blocked" in result.lower()
    finally:
        builtin_module.BASE_DIRECTORY = original_base
        if os.path.exists(env_path):
            os.unlink(env_path)


@pytest.mark.asyncio
async def test_file_read_sensitive_pem_blocked():
    """Test that reading .pem files is blocked."""
    original_base = builtin_module.BASE_DIRECTORY
    try:
        base = tempfile.mkdtemp()
        builtin_module.BASE_DIRECTORY = base
        pem_path = os.path.join(base, "server.pem")
        with open(pem_path, "w") as f:
            f.write("-----BEGIN CERTIFICATE-----")
        result = await file_read(path=pem_path)
        assert "error" in result.lower()
        assert "sensitive" in result.lower() or "blocked" in result.lower()
    finally:
        builtin_module.BASE_DIRECTORY = original_base
        if os.path.exists(pem_path):
            os.unlink(pem_path)


@pytest.mark.asyncio
async def test_file_read_sensitive_key_blocked():
    """Test that reading .key files is blocked."""
    original_base = builtin_module.BASE_DIRECTORY
    try:
        base = tempfile.mkdtemp()
        builtin_module.BASE_DIRECTORY = base
        key_path = os.path.join(base, "private.key")
        with open(key_path, "w") as f:
            f.write("secret key data")
        result = await file_read(path=key_path)
        assert "error" in result.lower()
        assert "sensitive" in result.lower() or "blocked" in result.lower()
    finally:
        builtin_module.BASE_DIRECTORY = original_base
        if os.path.exists(key_path):
            os.unlink(key_path)


def test_validate_path_blocks_traversal():
    """Test _validate_path with path traversal attempts."""
    original_base = builtin_module.BASE_DIRECTORY
    try:
        base = tempfile.mkdtemp()
        builtin_module.BASE_DIRECTORY = base
        with pytest.raises(ValueError, match="traversal"):
            if sys.platform == "win32":
                _validate_path("C:\\Windows\\System32\\cmd.exe")
            else:
                _validate_path("/etc/passwd")
    finally:
        builtin_module.BASE_DIRECTORY = original_base


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
