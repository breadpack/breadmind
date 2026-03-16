"""Sandbox for shell command execution — foundation for container isolation."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Commands that should never be executed without explicit approval
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/",           # rm -rf /
    r"\bmkfs\b",                  # format filesystem
    r"\bdd\s+.*of=/dev/",        # dd to device
    r":(){.*};:",                  # fork bomb
    r"\bshutdown\b",             # shutdown
    r"\breboot\b",               # reboot (without context)
    r"\biptables\s+-F\b",        # flush iptables
    r"\bkubectl\s+delete\s+.*--all", # kubectl delete --all
]


@dataclass
class SandboxConfig:
    max_execution_time: int = 30  # seconds
    max_output_size: int = 50_000  # chars
    allow_network: bool = True
    blocked_patterns: list[str] | None = None


class CommandSandbox:
    """Validate and execute shell commands with safety checks."""

    def __init__(self, config: SandboxConfig | None = None):
        self._config = config or SandboxConfig()
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (self._config.blocked_patterns or DANGEROUS_PATTERNS)
        ]

    def validate(self, command: str) -> tuple[bool, str]:
        """Check if a command is safe to execute. Returns (is_safe, reason)."""
        for pattern in self._compiled_patterns:
            if pattern.search(command):
                return False, f"Command matches dangerous pattern: {pattern.pattern}"
        return True, "ok"

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[bool, str]:
        """Execute a command with timeout and output limits."""
        is_safe, reason = self.validate(command)
        if not is_safe:
            return False, f"[BLOCKED] {reason}"

        effective_timeout = timeout or self._config.max_execution_time
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > self._config.max_output_size:
                output = output[: self._config.max_output_size] + "\n[...truncated]"
            return proc.returncode == 0, output
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return False, f"Command timed out after {effective_timeout}s"
        except Exception as e:
            return False, f"Execution error: {e}"
