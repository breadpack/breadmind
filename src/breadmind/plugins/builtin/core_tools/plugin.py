"""Core tools plugin -- shell execution, web search, file I/O.

Security helpers and shell execution are in separate modules:
- security.py: ToolSecurityConfig, path/command validation
- shell_tool.py: shell_exec tool implementation
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from breadmind.plugins.builtin.core_tools.security import (
    ALLOWED_SSH_HOSTS,
    BASE_DIRECTORY,
    DANGEROUS_PATTERNS,
    SENSITIVE_FILE_PATTERNS,
    SHELL_META_CHARS,
    ToolSecurityConfig,
    get_known_hosts as _get_known_hosts,
    has_shell_metacharacters as _has_shell_metacharacters,
    is_command_allowed as _is_command_allowed,
    is_dangerous_command as _is_dangerous_command,
    validate_path as _validate_path,
)
from breadmind.plugins.builtin.core_tools.shell_tool import shell_exec  # noqa: F401
from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


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
    # shell_exec (delegated to shell_tool module)
    # ------------------------------------------------------------------
    shell_exec = shell_exec

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
