"""Shell execution tool implementation."""
from __future__ import annotations

import asyncio
import logging
import shlex
import sys

from breadmind.plugins.builtin.core_tools.security import (
    ToolSecurityConfig,
    get_known_hosts,
    has_shell_metacharacters,
    is_command_allowed,
)
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


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
    import re as _re

    # Redirect SSH commands to router_manage for secure credential handling
    if _re.search(r'\bssh\b', command) and host == "localhost":
        return (
            "[REDIRECT] SSH 연결은 shell_exec 대신 router_manage 도구를 사용해야 합니다. "
            "지금 즉시 router_manage(action='connect', host='대상IP', "
            "router_type='openwrt', username='root') 를 호출하세요. "
            "password가 없으면 빈 문자열로 호출하면 자격증명 입력 폼이 자동 생성됩니다."
        )

    # Check if command is allowed (whitelist + blacklist)
    allowed, reason = is_command_allowed(command)
    if not allowed:
        return f"Error: Command blocked - {reason}: {command}"

    # Container isolation mode
    if container and host == "localhost":
        try:
            from breadmind.core.sandbox import ContainerExecutor
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
        needs_shell = has_shell_metacharacters(command)

        try:
            if needs_shell:
                logger.debug("Using subprocess_shell for command with metacharacters")
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            elif is_windows:
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
            known_hosts = get_known_hosts()
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
