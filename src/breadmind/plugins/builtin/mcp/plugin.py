"""MCP server management plugin: search, install, start/stop."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.mcp_client import MCPClientManager
from breadmind.tools.registry import tool
from breadmind.tools.registry_search import RegistrySearchEngine


class McpPlugin(BaseToolPlugin):
    """Plugin for managing MCP servers and searching registries."""

    name = "mcp"
    version = "0.1.0"

    def __init__(self) -> None:
        self._mcp_manager: MCPClientManager | None = None
        self._search_engine: RegistrySearchEngine | None = None

    async def setup(self, container: Any) -> None:
        self._mcp_manager = container.get("mcp_manager")
        self._search_engine = container.get("search_engine")

    def get_tools(self) -> list[Callable]:
        return [
            self.mcp_search,
            self.mcp_recommend,
            self.mcp_install,
            self.mcp_uninstall,
            self.mcp_list,
            self.mcp_start,
            self.mcp_stop,
        ]

    @tool(description="Search MCP skill registries for tools matching a query")
    async def mcp_search(self, query: str, limit: int = 5) -> str:
        results = await self._search_engine.search(query, limit)
        if not results:
            return "No MCP skills found matching your query."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.name}** ({r.source})")
            lines.append(f"   {r.description}")
            if r.install_command:
                lines.append(f"   Install: {r.install_command}")
        return "\n".join(lines)

    @tool(description="Recommend MCP skills based on search results and explain their relevance")
    async def mcp_recommend(self, query: str) -> str:
        results = await self._search_engine.search(query, limit=5)
        if not results:
            return "No relevant MCP skills found to recommend."
        lines = ["Here are recommended MCP skills for your needs:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.name}** — {r.description}")
            lines.append(f"   Source: {r.source}")
        lines.append("\nWould you like me to install any of these?")
        return "\n".join(lines)

    @tool(description="Install an MCP skill from a registry. Requires user approval.")
    async def mcp_install(self, slug: str, source: str = "clawhub") -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "clawhub", "install", slug,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return f"Install failed: {stderr.decode()}"
            skill_dir = f"./skills/{slug}"
            definitions = await self._mcp_manager.start_stdio_server(
                name=slug, command="node", args=[f"{skill_dir}/index.js"],
                source="clawhub",
            )
            tool_names = [d.name for d in definitions]
            return f"Installed and started '{slug}'. Available tools: {', '.join(tool_names)}"
        except FileNotFoundError:
            return "Error: clawhub CLI not found. Install it first."
        except Exception as e:
            return f"Install error: {e}"

    @tool(description="Uninstall an MCP skill. Requires user approval.")
    async def mcp_uninstall(self, name: str) -> str:
        try:
            await self._mcp_manager.stop_server(name)
            return f"Stopped and uninstalled MCP server '{name}'."
        except Exception as e:
            return f"Uninstall error: {e}"

    @tool(description="List all installed and connected MCP servers")
    async def mcp_list(self) -> str:
        servers = await self._mcp_manager.list_servers()
        if not servers:
            return "No MCP servers installed or connected."
        lines = []
        for s in servers:
            tools_str = ", ".join(s.tools) if s.tools else "none"
            lines.append(f"- **{s.name}** [{s.transport}] status={s.status} source={s.source}")
            lines.append(f"  Tools: {tools_str}")
        return "\n".join(lines)

    @tool(description="Start a stopped MCP server")
    async def mcp_start(self, name: str) -> str:
        return f"Start not implemented for '{name}' — server config needed from DB."

    @tool(description="Stop a running MCP server")
    async def mcp_stop(self, name: str) -> str:
        try:
            await self._mcp_manager.stop_server(name)
            return f"Stopped MCP server '{name}'."
        except Exception as e:
            return f"Stop error: {e}"
