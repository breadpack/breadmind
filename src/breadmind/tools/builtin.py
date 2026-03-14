import asyncio
import fnmatch
import os
import shlex
import sys
from pathlib import Path
from breadmind.tools.registry import tool

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


def _is_dangerous_command(command: str) -> bool:
    """Check if a command matches any dangerous pattern."""
    cmd_lower = command.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in cmd_lower:
            return True
    return False


def _validate_path(path: str) -> Path:
    """Validate that a path doesn't escape the base directory or access sensitive files.

    Returns the resolved Path if valid, raises ValueError otherwise.
    """
    p = Path(path).resolve()
    base = Path(BASE_DIRECTORY).resolve()

    # Check symlink traversal: resolved path must be under base
    try:
        p.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: {path} resolves outside base directory {base}"
        )

    # Check sensitive file patterns
    filename = p.name
    for pattern in SENSITIVE_FILE_PATTERNS:
        if fnmatch.fnmatch(filename.lower(), pattern.lower()):
            raise ValueError(f"Access to sensitive file blocked: {filename}")

    return p


@tool(description="Execute a shell command locally or via SSH. Use host='localhost' for local commands.")
async def shell_exec(command: str, host: str = "localhost", timeout: int = 30) -> str:
    # Check for dangerous commands
    if _is_dangerous_command(command):
        return f"Error: Command blocked - matches dangerous pattern: {command}"

    if host == "localhost":
        try:
            args = shlex.split(command)
        except ValueError as e:
            return f"Error: Failed to parse command: {e}"

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return f"Error: Command not found: {args[0] if args else command}"
        except OSError as e:
            return f"Error: Failed to execute command: {e}"

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout}s: {command}")

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")
        result = output
        if errors:
            result += f"\nSTDERR: {errors}"
        if proc.returncode != 0:
            result += f"\nExit code: {proc.returncode}"
        return result.strip()
    else:
        # Validate SSH host
        if ALLOWED_SSH_HOSTS and host not in ALLOWED_SSH_HOSTS:
            return f"Error: SSH host not allowed: {host}. Allowed hosts: {ALLOWED_SSH_HOSTS}"

        try:
            import asyncssh
        except ImportError:
            return "Error: asyncssh not installed. Install with: pip install asyncssh"
        try:
            async with asyncssh.connect(host) as conn:
                result = await asyncio.wait_for(conn.run(command), timeout=timeout)
                output = result.stdout or ""
                if result.stderr:
                    output += f"\nSTDERR: {result.stderr}"
                return output.strip()
        except Exception as e:
            return f"SSH error: {e}"


@tool(description="Search the web for information using DuckDuckGo")
async def web_search(query: str, limit: int = 5) -> str:
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


async def _duckduckgo_search(query: str, limit: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=limit))
    except ImportError:
        return [{"title": "Error", "href": "", "body": "duckduckgo-search not installed"}]
    except Exception as e:
        return [{"title": "Error", "href": "", "body": str(e)}]


@tool(description="Read content from a file")
async def file_read(path: str, encoding: str = "utf-8") -> str:
    try:
        p = _validate_path(path)
        if not p.exists():
            return f"Error: File not found: {path}"
        return p.read_text(encoding=encoding)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool(description="Write content to a file")
async def file_write(path: str, content: str, encoding: str = "utf-8") -> str:
    try:
        p = _validate_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"Written {len(content)} bytes to {path}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing file: {e}"
