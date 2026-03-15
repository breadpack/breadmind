import pytest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.tools.builtin import (
    shell_exec, web_search, file_read, file_write,
    _is_dangerous_command, _is_command_allowed, _validate_path,
    DANGEROUS_PATTERNS, BASE_DIRECTORY,
    ToolSecurityConfig,
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
    # Set allowed hosts via ToolSecurityConfig (shell_exec reads from there)
    original = list(ToolSecurityConfig._allowed_ssh_hosts)
    try:
        ToolSecurityConfig.update(allowed_ssh_hosts=["trusted.example.com"])
        result = await shell_exec(command="echo hi", host="evil.example.com", timeout=5)
        assert "not allowed" in result.lower()
    finally:
        ToolSecurityConfig._allowed_ssh_hosts = original


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


# --- SSH parameter tests ---

def test_shell_exec_has_port_username_key_file_params():
    """Verify shell_exec accepts port, username, key_file parameters."""
    defn = shell_exec._tool_definition
    props = defn.parameters.get("properties", {})
    assert "port" in props
    assert "username" in props
    assert "key_file" in props


@pytest.mark.asyncio
async def test_shell_exec_ssh_with_port_username_key_file():
    """Test SSH connect is called with port, username, key_file."""
    original = list(ToolSecurityConfig._allowed_ssh_hosts)
    try:
        ToolSecurityConfig.update(allowed_ssh_hosts=[])  # allow all

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.stdout = "success"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect.__aexit__ = AsyncMock(return_value=False)

        mock_asyncssh = MagicMock()
        mock_asyncssh.connect = MagicMock(return_value=mock_connect)

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            result = await shell_exec(
                command="uptime",
                host="myserver.example.com",
                timeout=10,
                port=2222,
                username="admin",
                key_file="/home/user/.ssh/id_rsa",
            )

            mock_asyncssh.connect.assert_called_once_with(
                host="myserver.example.com",
                port=2222,
                known_hosts=None,
                username="admin",
                client_keys=["/home/user/.ssh/id_rsa"],
            )
            assert "success" in result
    finally:
        ToolSecurityConfig._allowed_ssh_hosts = original


@pytest.mark.asyncio
async def test_shell_exec_ssh_default_port_no_username_no_key():
    """Test SSH connect with defaults: port=22, no username, no key_file."""
    original = list(ToolSecurityConfig._allowed_ssh_hosts)
    try:
        ToolSecurityConfig.update(allowed_ssh_hosts=[])  # allow all

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        mock_connect = MagicMock()
        mock_connect.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect.__aexit__ = AsyncMock(return_value=False)

        mock_asyncssh = MagicMock()
        mock_asyncssh.connect = MagicMock(return_value=mock_connect)

        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            result = await shell_exec(
                command="hostname",
                host="server.example.com",
                timeout=10,
            )

            mock_asyncssh.connect.assert_called_once_with(
                host="server.example.com",
                port=22,
                known_hosts=None,
            )
            assert "ok" in result
    finally:
        ToolSecurityConfig._allowed_ssh_hosts = original


# =========================================================================
# ToolSecurityConfig tests
# =========================================================================

@pytest.fixture(autouse=False)
def reset_security_config():
    """Reset ToolSecurityConfig after each test that uses it."""
    yield
    ToolSecurityConfig.reset()


def test_tool_security_config_update_dangerous_patterns(reset_security_config):
    ToolSecurityConfig.update(dangerous_patterns=["custom_danger"])
    assert ToolSecurityConfig._dangerous_patterns == ["custom_danger"]


def test_tool_security_config_update_allowed_ssh_hosts(reset_security_config):
    ToolSecurityConfig.update(allowed_ssh_hosts=["host1.example.com", "host2.example.com"])
    assert ToolSecurityConfig._allowed_ssh_hosts == ["host1.example.com", "host2.example.com"]


def test_tool_security_config_get_config(reset_security_config):
    config = ToolSecurityConfig.get_config()
    assert "dangerous_patterns" in config
    assert "sensitive_file_patterns" in config
    assert "allowed_ssh_hosts" in config
    assert "base_directory" in config


def test_tool_security_config_updated_dangerous_patterns_used_by_is_dangerous(reset_security_config):
    """Test that _is_dangerous_command uses ToolSecurityConfig patterns."""
    # Default should block "rm -rf /"
    assert _is_dangerous_command("rm -rf /") is True
    # Update to a custom list that does not include "rm -rf /"
    ToolSecurityConfig.update(dangerous_patterns=["custom_only"])
    assert _is_dangerous_command("rm -rf /") is False
    assert _is_dangerous_command("custom_only something") is True


@pytest.mark.asyncio
async def test_tool_security_config_updated_ssh_hosts_used_by_shell_exec(reset_security_config):
    """Test that shell_exec uses ToolSecurityConfig for SSH host validation."""
    ToolSecurityConfig.update(allowed_ssh_hosts=["trusted.example.com"])
    result = await shell_exec(command="echo hi", host="evil.example.com", timeout=5)
    assert "not allowed" in result.lower()


# =========================================================================
# Command whitelist and _is_command_allowed tests
# =========================================================================


def test_is_command_allowed_dangerous_pattern(reset_security_config):
    """Test _is_command_allowed rejects dangerous patterns."""
    allowed, reason = _is_command_allowed("rm -rf /")
    assert allowed is False
    assert "dangerous pattern" in reason.lower()


def test_is_command_allowed_safe_command(reset_security_config):
    """Test _is_command_allowed accepts safe commands."""
    allowed, reason = _is_command_allowed("echo hello")
    assert allowed is True
    assert reason == ""


def test_whitelist_blocks_non_whitelisted(reset_security_config):
    """Test that whitelist mode blocks commands not in the whitelist."""
    ToolSecurityConfig.set_command_whitelist(["git", "ls"], enabled=True)
    allowed, reason = _is_command_allowed("curl http://evil.com")
    assert allowed is False
    assert "not in whitelist" in reason.lower()


def test_whitelist_allows_whitelisted(reset_security_config):
    """Test that whitelist mode allows whitelisted commands."""
    ToolSecurityConfig.set_command_whitelist(["git", "ls", "echo"], enabled=True)
    allowed, reason = _is_command_allowed("git status")
    assert allowed is True
    assert reason == ""


def test_whitelist_disabled_falls_back_to_blacklist(reset_security_config):
    """Test that disabled whitelist falls back to blacklist-only check."""
    ToolSecurityConfig.set_command_whitelist(["git"], enabled=False)
    # curl is not in whitelist, but whitelist is disabled so it should pass
    allowed, reason = _is_command_allowed("curl http://example.com")
    assert allowed is True

    # Dangerous command should still be blocked by blacklist
    allowed, reason = _is_command_allowed("rm -rf /")
    assert allowed is False


def test_whitelist_still_checks_blacklist(reset_security_config):
    """Test that even whitelisted commands are checked against blacklist."""
    ToolSecurityConfig.set_command_whitelist(["rm"], enabled=True)
    # "rm" is in whitelist, but "rm -rf /" matches dangerous pattern
    allowed, reason = _is_command_allowed("rm -rf /")
    assert allowed is False
    assert "dangerous pattern" in reason.lower()


@pytest.mark.asyncio
async def test_shell_exec_whitelist_blocks_command(reset_security_config):
    """Test that shell_exec respects whitelist mode."""
    ToolSecurityConfig.set_command_whitelist(["git"], enabled=True)
    if sys.platform == "win32":
        result = await shell_exec(command="cmd /c echo hello", host="localhost", timeout=5)
    else:
        result = await shell_exec(command="echo hello", host="localhost", timeout=5)
    assert "blocked" in result.lower()
    assert "not in whitelist" in result.lower()


def test_get_config_includes_whitelist(reset_security_config):
    """Test that get_config returns whitelist fields."""
    ToolSecurityConfig.set_command_whitelist(["git", "ls"], enabled=True)
    config = ToolSecurityConfig.get_config()
    assert config["command_whitelist"] == ["git", "ls"]
    assert config["command_whitelist_enabled"] is True


def test_reset_clears_whitelist(reset_security_config):
    """Test that reset clears whitelist settings."""
    ToolSecurityConfig.set_command_whitelist(["git"], enabled=True)
    ToolSecurityConfig.reset()
    config = ToolSecurityConfig.get_config()
    assert config["command_whitelist"] == []
    assert config["command_whitelist_enabled"] is False
