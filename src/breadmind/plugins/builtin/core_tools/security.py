"""Security helpers for core tools -- dangerous command detection, path validation."""
from __future__ import annotations

import fnmatch
import logging
import os
import re
from pathlib import Path

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

def get_known_hosts() -> str | None:
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

def is_dangerous_command(command: str) -> bool:
    """Check if a command matches any dangerous pattern."""
    cmd_lower = command.lower().strip()
    for pattern in ToolSecurityConfig._dangerous_patterns:
        if pattern.lower() in cmd_lower:
            return True
    return False


def has_shell_metacharacters(command: str) -> bool:
    """Return True if the command contains shell metacharacters (pipes, chains, etc.)."""
    return bool(SHELL_META_CHARS.search(command))


def is_command_allowed(command: str) -> tuple[bool, str]:
    """Check if command is allowed. Returns (allowed, reason)."""
    config = ToolSecurityConfig

    # Whitelist mode (if enabled, only whitelisted commands pass)
    if config._command_whitelist_enabled and config._command_whitelist:
        cmd_base = command.split()[0] if command.split() else ""
        if not any(cmd_base.startswith(w) for w in config._command_whitelist):
            return False, f"Command '{cmd_base}' not in whitelist"

    # Blacklist check (existing)
    if is_dangerous_command(command):
        return False, "Command matches dangerous pattern"

    return True, ""


def validate_path(path: str) -> Path:
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
