"""Core tools plugin — shell execution, web search, file I/O."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

DANGEROUS_PATTERNS: list[str] = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    ">()",
    "chmod -R 777 /",
]

SENSITIVE_FILE_PATTERNS: list[str] = [
    ".env",
    "*credentials*",
    "*secret*",
    "*.key",
    "*.pem",
]

# Configurable base directory for path validation
BASE_DIRECTORY: str = os.getcwd()

# Allowed SSH hosts (empty means all are blocked except localhost)
ALLOWED_SSH_HOSTS: list[str] = []

# Shell metacharacters that indicate potential command injection
SHELL_META_CHARS = re.compile(r'[;&|`$]')


# ---------------------------------------------------------------------------
# Helper: known_hosts for SSH
# ---------------------------------------------------------------------------

def _get_known_hosts() -> str | None:
    """Return the path to known_hosts for SSH host key verification.

    By default, uses ``~/.ssh/known_hosts`` (created if absent).
    Set ``BREADMIND_SSH_STRICT_HOST_KEY=false`` to explicitly disable verification.
    """
    strict = os.environ.get("BREADMIND_SSH_STRICT_HOST_KEY", "true").lower()
    if strict == "false":
        logger.warning(
            "SSH host key verification disabled by BREADMIND_SSH_STRICT_HOST_KEY=false"
        )
        return None
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if not known_hosts.exists():
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        known_hosts.touch(mode=0o644)
    return str(known_hosts)


# ---------------------------------------------------------------------------
# ToolSecurityConfig
# ---------------------------------------------------------------------------

class ToolSecurityConfig:
    """Runtime-configurable security settings for builtin tools."""

    _dangerous_patterns: list[str] = list(DANGEROUS_PATTERNS)
    _sensitive_patterns: list[str] = list(SENSITIVE_FILE_PATTERNS)
    _allowed_ssh_hosts: list[str] = list(ALLOWED_SSH_HOSTS)
    _base_directory: str = str(Path.cwd())
    _command_whitelist: list[str] = []  # If non-empty, only these commands allowed
    _command_whitelist_enabled: bool = False

    @classmethod
    def update(cls, dangerous_patterns=None, sensitive_patterns=None,
               allowed_ssh_hosts=None, base_directory=None):
        if dangerous_patterns is not None:
            cls._dangerous_patterns = dangerous_patterns
        if sensitive_patterns is not None:
            cls._sensitive_patterns = sensitive_patterns
        if allowed_ssh_hosts is not None:
            cls._allowed_ssh_hosts = allowed_ssh_hosts
        if base_directory is not None:
            cls._base_directory = base_directory

    @classmethod
    def set_command_whitelist(cls, commands: list[str], enabled: bool = True):
        cls._command_whitelist = commands
        cls._command_whitelist_enabled = enabled

    @classmethod
    def get_config(cls) -> dict:
        return {
            "dangerous_patterns": cls._dangerous_patterns,
            "sensitive_file_patterns": cls._sensitive_patterns,
            "allowed_ssh_hosts": cls._allowed_ssh_hosts,
            "base_directory": cls._base_directory,
            "command_whitelist": cls._command_whitelist,
            "command_whitelist_enabled": cls._command_whitelist_enabled,
        }

    @classmethod
    def reset(cls):
        """Reset to module-level defaults."""
        cls._dangerous_patterns = list(DANGEROUS_PATTERNS)
        cls._sensitive_patterns = list(SENSITIVE_FILE_PATTERNS)
        cls._allowed_ssh_hosts = list(ALLOWED_SSH_HOSTS)
        cls._base_directory = str(Path.cwd())
        cls._command_whitelist = []
        cls._command_whitelist_enabled = False


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _is_dangerous_command(command: str) -> bool:
    """Check if a command matches any dangerous pattern."""
    cmd_lower = command.lower().strip()
    for pattern in ToolSecurityConfig._dangerous_patterns:
        if pattern.lower() in cmd_lower:
            return True
    return False


def _has_shell_metacharacters(command: str) -> bool:
    """Return True if the command contains shell metacharacters (pipes, chains, etc.)."""
    return bool(SHELL_META_CHARS.search(command))


def _is_command_allowed(command: str) -> tuple[bool, str]:
    """Check if command is allowed. Returns (allowed, reason)."""
    config = ToolSecurityConfig

    # Whitelist mode (if enabled, only whitelisted commands pass)
    if config._command_whitelist_enabled and config._command_whitelist:
        cmd_base = command.split()[0] if command.split() else ""
        if not any(cmd_base.startswith(w) for w in config._command_whitelist):
            return False, f"Command '{cmd_base}' not in whitelist"

    # Blacklist check (existing)
    if _is_dangerous_command(command):
        return False, "Command matches dangerous pattern"

    return True, ""


def _validate_path(path: str) -> Path:
    """Validate that a path doesn't escape the base directory or access sensitive files.

    Returns the resolved Path if valid, raises ValueError otherwise.
    """
    p = Path(path).resolve()
    base = Path(ToolSecurityConfig._base_directory).resolve()

    # Check symlink traversal: resolved path must be under base
    try:
        p.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: {path} resolves outside base directory {base}"
        )

    # Block symbolic link access (resolve() already followed the link above,
    # but we explicitly reject symlinks to prevent confusion)
    if Path(path).is_symlink():
        raise ValueError(f"Symbolic link access blocked: {path}")

    # Check sensitive file patterns against filename AND every path component
    for pattern in ToolSecurityConfig._sensitive_patterns:
        if fnmatch.fnmatch(p.name.lower(), pattern.lower()):
            raise ValueError(f"Access to sensitive file blocked: {p.name}")
        for part in p.parts:
            if fnmatch.fnmatch(part.lower(), pattern.lower()):
                raise ValueError(f"Access to sensitive path blocked: {path}")

    return p


# ---------------------------------------------------------------------------
# DuckDuckGo search helper
# ---------------------------------------------------------------------------

async def _duckduckgo_search(query: str, limit: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=limit))
    except ImportError:
        return [{"title": "Error", "href": "", "body": "duckduckgo-search not installed"}]
    except Exception as e:
        return [{"title": "Error", "href": "", "body": str(e)}]


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

class CoreToolsPlugin(BaseToolPlugin):
    """Core system tools: shell execution, web search, file I/O."""

    name = "core-tools"
    version = "0.1.0"

    def get_tools(self) -> list[Callable]:
        return [self.shell_exec, self.web_search, self.file_read, self.file_write]

    async def setup(self, container: Any) -> None:
        pass

    # ------------------------------------------------------------------
    # shell_exec
    # ------------------------------------------------------------------
    @tool(description="Execute a shell command locally, via SSH, or in an isolated Docker container. Use host='localhost' for local commands. Set container=True for Docker isolation.")
    async def shell_exec(
        self,
        command: str,
        host: str = "localhost",
        timeout: int = 30,
        port: int = 22,
        username: str = None,
        key_file: str = None,
        container: bool = False,
        image: str = None,
    ) -> str:
        # Redirect SSH commands to router_manage for secure credential handling
        import re as _re
        if _re.search(r'\bssh\b', command) and host == "localhost":
            return (
                "[REDIRECT] SSH 연결은 shell_exec 대신 router_manage 도구를 사용해야 합니다. "
                "지금 즉시 router_manage(action='connect', host='대상IP', "
                "router_type='openwrt', username='root') 를 호출하세요. "
                "password가 없으면 빈 문자열로 호출하면 자격증명 입력 폼이 자동 생성됩니다."
            )

        # Check if command is allowed (whitelist + blacklist)
        allowed, reason = _is_command_allowed(command)
        if not allowed:
            return f"Error: Command blocked - {reason}: {command}"

        # Container isolation mode
        if container and host == "localhost":
            try:
                from breadmind.core.container import ContainerExecutor
                executor = ContainerExecutor()
                result = await executor.run_command(command, image=image, timeout=timeout)
                if result.error:
                    return f"Container error: {result.error}"
                output = result.stdout
                if result.exit_code != 0:
                    output += f"\nExit code: {result.exit_code}"
                return output.strip() if output else "(no output)"
            except Exception as e:
                return f"Container execution failed: {e}"

        if host == "localhost":
            is_windows = sys.platform == "win32"
            needs_shell = _has_shell_metacharacters(command)

            try:
                if needs_shell:
                    # Shell required for pipes, chains, etc. — already validated
                    # by _is_command_allowed above
                    logger.debug("Using subprocess_shell for command with metacharacters")
                    proc = await asyncio.create_subprocess_shell(
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                elif is_windows:
                    # Windows without metacharacters: still use shell for cmd built-ins
                    proc = await asyncio.create_subprocess_shell(
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                else:
                    args = shlex.split(command)
                    proc = await asyncio.create_subprocess_exec(
                        *args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
            except FileNotFoundError:
                return f"Error: Command not found: {command}"
            except OSError as e:
                return f"Error: Failed to execute command: {e}"

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise TimeoutError(f"Command timed out after {timeout}s: {command}")

            encoding = "cp949" if is_windows else "utf-8"
            output = stdout.decode(encoding, errors="replace")
            errors = stderr.decode(encoding, errors="replace")
            result = output
            if errors:
                result += f"\nSTDERR: {errors}"
            if proc.returncode != 0:
                result += f"\nExit code: {proc.returncode}"
            return result.strip()
        else:
            # Validate SSH host
            if ToolSecurityConfig._allowed_ssh_hosts and host not in ToolSecurityConfig._allowed_ssh_hosts:
                return f"Error: SSH host not allowed: {host}. Allowed hosts: {ToolSecurityConfig._allowed_ssh_hosts}"

            try:
                import asyncssh
            except ImportError:
                return "Error: asyncssh not installed. Install with: pip install asyncssh"
            try:
                known_hosts = _get_known_hosts()
                if known_hosts is None:
                    logger.warning(
                        "SSH connection to %s:%d with known_hosts=None — "
                        "host key verification is disabled", host, port,
                    )
                connect_kwargs: dict = {
                    "host": host,
                    "port": port,
                    "known_hosts": known_hosts,
                }
                if username is not None:
                    connect_kwargs["username"] = username
                if key_file is not None:
                    connect_kwargs["client_keys"] = [key_file]
                async with asyncssh.connect(**connect_kwargs) as conn:
                    result = await asyncio.wait_for(conn.run(command), timeout=timeout)
                    output = result.stdout or ""
                    if result.stderr:
                        output += f"\nSTDERR: {result.stderr}"
                    return output.strip()
            except Exception as e:
                return f"SSH error: {e}"

    # ------------------------------------------------------------------
    # web_search
    # ------------------------------------------------------------------
    @tool(description="Search the web for information using DuckDuckGo")
    async def web_search(self, query: str, limit: int = 5) -> str:
        results = await _duckduckgo_search(query, limit)
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"**{r.get('title', 'No title')}**")
            lines.append(f"  URL: {r.get('href', '')}")
            lines.append(f"  {r.get('body', '')}")
            lines.append("")
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # file_read
    # ------------------------------------------------------------------
    @tool(description="Read content from a file")
    async def file_read(self, path: str, encoding: str = "utf-8") -> str:
        try:
            p = _validate_path(path)
            if not p.exists():
                return f"Error: File not found: {path}"
            return p.read_text(encoding=encoding)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {e}"

    # ------------------------------------------------------------------
    # file_write
    # ------------------------------------------------------------------
    @tool(description="Write content to a file")
    async def file_write(self, path: str, content: str, encoding: str = "utf-8") -> str:
        try:
            p = _validate_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
            return f"Written {len(content)} bytes to {path}"
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {e}"
