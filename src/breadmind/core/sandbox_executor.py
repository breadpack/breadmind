"""Sandbox execution wrapper that isolates tool execution.

Provides filesystem-level and Docker-level isolation for shell commands,
with path validation, environment sanitization, and resource limits.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Environment variable patterns that should be stripped before subprocess execution
_SENSITIVE_ENV_PATTERNS = re.compile(
    r".*(_KEY|_SECRET|_TOKEN|_PASSWORD)$", re.IGNORECASE,
)

# Default paths that are always blocked
DEFAULT_BLOCKED_PATHS: list[str] = [
    "/etc/shadow",
    "/etc/passwd",
    "~/.ssh",
    "~/.aws",
    "~/.config/gcloud",
]


class SandboxMode(enum.Enum):
    """Isolation level for command execution."""

    NONE = "none"
    FILESYSTEM = "filesystem"
    DOCKER = "docker"


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution."""

    mode: SandboxMode = SandboxMode.FILESYSTEM
    allowed_paths: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_PATHS))
    network_allowed: bool = True
    max_memory_mb: int = 512
    timeout_seconds: int = 30
    docker_image: str = "python:3.12-slim"


@dataclass
class SandboxResult:
    """Result of a sandboxed command execution."""

    success: bool
    output: str
    exit_code: int
    mode_used: SandboxMode


class SandboxExecutor:
    """Execute commands with configurable sandbox isolation."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        # Expand ~ in blocked paths once at init time
        self._expanded_blocked: list[str] = [
            os.path.expanduser(p) for p in self._config.blocked_paths
        ]

    # ── Public API ────────────────────────────────────────────────────

    async def execute(
        self, command: str, workdir: str | None = None,
    ) -> SandboxResult:
        """Execute *command* under the configured sandbox constraints."""
        mode = self._config.mode

        if mode == SandboxMode.NONE:
            return await self._execute_no_sandbox(command, workdir)

        if mode == SandboxMode.FILESYSTEM:
            return await self._execute_filesystem_mode(command, workdir)

        if mode == SandboxMode.DOCKER:
            return await self._execute_docker_mode(command, workdir)

        return SandboxResult(
            success=False,
            output=f"Unknown sandbox mode: {mode}",
            exit_code=-1,
            mode_used=mode,
        )

    def validate_path(self, path: str) -> bool:
        """Check whether *path* is within allowed boundaries.

        Resolves symlinks so that a symlink pointing outside allowed
        directories is correctly rejected.
        """
        resolved = os.path.realpath(os.path.expanduser(path))

        # Check blocked paths first
        for blocked in self._expanded_blocked:
            blocked_resolved = os.path.realpath(blocked)
            if resolved == blocked_resolved or resolved.startswith(blocked_resolved + os.sep):
                return False

        # If allowed_paths is configured, the resolved path must fall
        # inside at least one of them.
        if self._config.allowed_paths:
            for allowed in self._config.allowed_paths:
                allowed_resolved = os.path.realpath(os.path.expanduser(allowed))
                if resolved == allowed_resolved or resolved.startswith(allowed_resolved + os.sep):
                    return True
            return False

        return True

    # ── Filesystem access check ───────────────────────────────────────

    def _check_filesystem_access(self, command: str) -> bool:
        """Validate paths referenced in *command* against allowed/blocked lists.

        Performs a best-effort extraction of paths from the command string.
        Returns ``True`` if the command passes validation.
        """
        # Extract tokens that look like absolute paths or ~-relative paths
        tokens = re.findall(r"(?:/[\w./-]+|~[\w./-]*)", command)
        for token in tokens:
            if not self.validate_path(token):
                logger.warning("Blocked filesystem access to %s", token)
                return False
        return True

    # ── Execution backends ────────────────────────────────────────────

    async def _execute_no_sandbox(
        self, command: str, workdir: str | None,
    ) -> SandboxResult:
        """Run command without any isolation (passthrough)."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.timeout_seconds,
            )
            output = stdout.decode("utf-8", errors="replace")
            return SandboxResult(
                success=proc.returncode == 0,
                output=output,
                exit_code=proc.returncode or 0,
                mode_used=SandboxMode.NONE,
            )
        except asyncio.TimeoutError:
            return SandboxResult(
                success=False,
                output=f"Command timed out after {self._config.timeout_seconds}s",
                exit_code=-1,
                mode_used=SandboxMode.NONE,
            )

    async def _execute_filesystem_mode(
        self, command: str, workdir: str | None,
    ) -> SandboxResult:
        """Run command with filesystem access restrictions and env sanitization."""
        if not self._check_filesystem_access(command):
            return SandboxResult(
                success=False,
                output="Command blocked: references a restricted path",
                exit_code=-1,
                mode_used=SandboxMode.FILESYSTEM,
            )

        env = self._sanitized_env()

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.timeout_seconds,
            )
            output = stdout.decode("utf-8", errors="replace")
            return SandboxResult(
                success=proc.returncode == 0,
                output=output,
                exit_code=proc.returncode or 0,
                mode_used=SandboxMode.FILESYSTEM,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[union-attr]
            except Exception:
                pass
            return SandboxResult(
                success=False,
                output=f"Command timed out after {self._config.timeout_seconds}s",
                exit_code=-1,
                mode_used=SandboxMode.FILESYSTEM,
            )

    async def _execute_docker_mode(
        self, command: str, workdir: str | None,
    ) -> SandboxResult:
        """Wrap execution in ``docker run --rm --read-only``."""
        docker_cmd = self._build_docker_command(command, workdir)

        try:
            proc = await asyncio.create_subprocess_shell(
                docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.timeout_seconds,
            )
            output = stdout.decode("utf-8", errors="replace")
            return SandboxResult(
                success=proc.returncode == 0,
                output=output,
                exit_code=proc.returncode or 0,
                mode_used=SandboxMode.DOCKER,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()  # type: ignore[union-attr]
            except Exception:
                pass
            return SandboxResult(
                success=False,
                output=f"Command timed out after {self._config.timeout_seconds}s",
                exit_code=-1,
                mode_used=SandboxMode.DOCKER,
            )

    # ── Helpers ───────────────────────────────────────────────────────

    def _build_docker_command(self, command: str, workdir: str | None) -> str:
        """Build the full ``docker run`` invocation."""
        parts = [
            "docker", "run", "--rm", "--read-only",
            f"--memory={self._config.max_memory_mb}m",
            "--tmpfs", "/tmp:size=64M",
        ]

        if not self._config.network_allowed:
            parts.append("--network=none")

        # Bind-mount allowed paths as read-only
        for path in self._config.allowed_paths:
            expanded = os.path.expanduser(path)
            parts.extend(["-v", f"{expanded}:{expanded}:ro"])

        if workdir:
            parts.extend(["-w", workdir])

        parts.append(self._config.docker_image)
        parts.extend(["sh", "-c", command])

        return " ".join(parts)

    @staticmethod
    def _sanitized_env() -> dict[str, str]:
        """Return a copy of the current environment with sensitive vars removed."""
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            if _SENSITIVE_ENV_PATTERNS.match(key):
                continue
            env[key] = value
        return env
