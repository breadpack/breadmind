"""ToolGapDetector: detects missing tools and suggests MCP server installations."""
import time
from dataclasses import dataclass, field
from typing import Any

from breadmind.utils.helpers import generate_short_id

_MAX_PENDING = 10
_CACHE_TTL = 600  # 10 minutes


@dataclass
class MCPSuggestion:
    id: str
    tool_name: str
    mcp_name: str
    mcp_description: str
    install_command: str | None
    source: str
    status: str = "pending"


@dataclass
class ToolGapResult:
    resolved: bool
    message: str
    suggestions: list[MCPSuggestion] = field(default_factory=list)


class ToolGapDetector:
    """Detects when LLM requests a tool that doesn't exist and suggests MCP installations."""

    def __init__(self, tool_registry, mcp_manager, search_engine):
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._search_engine = search_engine
        # Cache: tool_name -> (timestamp, list[MCPSuggestion])
        self._search_cache: dict[str, tuple[float, list[MCPSuggestion]]] = {}
        # Pending installs: id -> MCPSuggestion
        self._pending: dict[str, MCPSuggestion] = {}
        # Gap history: list of dicts
        self._gap_history: list[dict] = []

    async def check_and_resolve(
        self, tool_name: str, args: dict[str, Any], user: str, channel: str
    ) -> ToolGapResult:
        """Check if a tool is missing and search registries for matching MCP servers."""
        # If tool exists, nothing to do
        existing = self._tool_registry.get_tool(tool_name)
        if existing is not None:
            return ToolGapResult(resolved=True, message=f"Tool '{tool_name}' is available.")

        # Record gap
        self._gap_history.append({
            "tool_name": tool_name,
            "user": user,
            "channel": channel,
            "timestamp": time.time(),
        })

        # Check cache
        cached = self._get_cached_suggestions(tool_name)
        if cached is not None:
            return ToolGapResult(
                resolved=False,
                message=f"Tool '{tool_name}' not found. {len(cached)} MCP server(s) available.",
                suggestions=cached,
            )

        # Search registries
        try:
            results = await self._search_engine.search(tool_name)
        except Exception as exc:
            return ToolGapResult(
                resolved=False,
                message=f"Tool '{tool_name}' not found. Search failed: {exc}",
                suggestions=[],
            )

        suggestions = []
        for r in results:
            suggestion = MCPSuggestion(
                id=generate_short_id(),
                tool_name=tool_name,
                mcp_name=r.name,
                mcp_description=r.description,
                install_command=r.install_command,
                source=r.source,
                status="pending",
            )
            suggestions.append(suggestion)
            self._add_pending(suggestion)

        # Cache results
        self._search_cache[tool_name] = (time.monotonic(), suggestions)

        if suggestions:
            message = f"Tool '{tool_name}' not found. {len(suggestions)} MCP server(s) available."
        else:
            message = f"Tool '{tool_name}' not found. No matching MCP servers found."

        return ToolGapResult(resolved=False, message=message, suggestions=suggestions)

    async def search_for_capability(self, description: str) -> list[MCPSuggestion]:
        """Search registries for MCP servers that provide a given capability."""
        try:
            results = await self._search_engine.search(description)
        except Exception:
            return []

        suggestions = []
        for r in results:
            suggestion = MCPSuggestion(
                id=generate_short_id(),
                tool_name=description,
                mcp_name=r.name,
                mcp_description=r.description,
                install_command=r.install_command,
                source=r.source,
                status="pending",
            )
            suggestions.append(suggestion)

        return suggestions

    def get_pending_installs(self) -> list[dict]:
        """Return all pending MCP installation suggestions."""
        return [
            {
                "id": s.id,
                "tool_name": s.tool_name,
                "mcp_name": s.mcp_name,
                "mcp_description": s.mcp_description,
                "install_command": s.install_command,
                "source": s.source,
                "status": s.status,
            }
            for s in self._pending.values()
            if s.status == "pending"
        ]

    async def approve_install(self, suggestion_id: str) -> str:
        """Approve and execute installation of a suggested MCP server."""
        suggestion = self._pending.get(suggestion_id)
        if suggestion is None:
            return f"Suggestion '{suggestion_id}' not found."

        install_cmd = suggestion.install_command or ""
        parts = install_cmd.split()
        if not parts:
            suggestion.status = "failed"
            return f"Installation failed for '{suggestion.mcp_name}': no install command."

        command = parts[0]
        args = parts[1:]

        try:
            tools = await self._mcp_manager.start_stdio_server(
                suggestion.mcp_name, command, args
            )
            suggestion.status = "installed"
            tool_count = len(tools) if tools else 0
            return f"Installed '{suggestion.mcp_name}' successfully. {tool_count} tool(s) registered."
        except Exception as exc:
            suggestion.status = "failed"
            return f"Installation failed for '{suggestion.mcp_name}': {exc}"

    async def deny_install(self, suggestion_id: str) -> None:
        """Deny and remove a pending installation suggestion."""
        suggestion = self._pending.pop(suggestion_id, None)
        if suggestion is not None:
            suggestion.status = "denied"

    def _add_pending(self, suggestion: MCPSuggestion) -> None:
        """Add a suggestion to pending installs with FIFO eviction at max capacity."""
        if len(self._pending) >= _MAX_PENDING:
            # Evict the oldest entry (first inserted)
            oldest_key = next(iter(self._pending))
            del self._pending[oldest_key]
        self._pending[suggestion.id] = suggestion

    def _get_cached_suggestions(self, tool_name: str) -> list[MCPSuggestion] | None:
        """Return cached suggestions if still within TTL, else None."""
        entry = self._search_cache.get(tool_name)
        if entry is None:
            return None
        ts, suggestions = entry
        if time.monotonic() - ts > _CACHE_TTL:
            del self._search_cache[tool_name]
            return None
        return suggestions

    @property
    def gap_history(self) -> list[dict]:
        """Return the history of tool gap events."""
        return list(self._gap_history)
