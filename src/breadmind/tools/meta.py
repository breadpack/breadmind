from breadmind.tools.registry import tool
from breadmind.tools.mcp_client import MCPClientManager
from breadmind.tools.registry_search import RegistrySearchEngine


def create_meta_tools(
    mcp_manager: MCPClientManager,
    search_engine: RegistrySearchEngine,
) -> dict:

    @tool(description="Search MCP skill registries for tools matching a query")
    async def mcp_search(query: str, limit: int = 5) -> str:
        results = await search_engine.search(query, limit)
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
    async def mcp_recommend(query: str) -> str:
        results = await search_engine.search(query, limit=5)
        if not results:
            return "No relevant MCP skills found to recommend."
        lines = ["Here are recommended MCP skills for your needs:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.name}** — {r.description}")
            lines.append(f"   Source: {r.source}")
        lines.append("\nWould you like me to install any of these?")
        return "\n".join(lines)

    @tool(description="Install an MCP skill from a registry. Requires user approval.")
    async def mcp_install(slug: str, source: str = "clawhub") -> str:
        import asyncio
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
            definitions = await mcp_manager.start_stdio_server(
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
    async def mcp_uninstall(name: str) -> str:
        try:
            await mcp_manager.stop_server(name)
            return f"Stopped and uninstalled MCP server '{name}'."
        except Exception as e:
            return f"Uninstall error: {e}"

    @tool(description="List all installed and connected MCP servers")
    async def mcp_list() -> str:
        servers = await mcp_manager.list_servers()
        if not servers:
            return "No MCP servers installed or connected."
        lines = []
        for s in servers:
            tools_str = ", ".join(s.tools) if s.tools else "none"
            lines.append(f"- **{s.name}** [{s.transport}] status={s.status} source={s.source}")
            lines.append(f"  Tools: {tools_str}")
        return "\n".join(lines)

    @tool(description="Start a stopped MCP server")
    async def mcp_start(name: str) -> str:
        return f"Start not implemented for '{name}' — server config needed from DB."

    @tool(description="Stop a running MCP server")
    async def mcp_stop(name: str) -> str:
        try:
            await mcp_manager.stop_server(name)
            return f"Stopped MCP server '{name}'."
        except Exception as e:
            return f"Stop error: {e}"

    return {
        "mcp_search": mcp_search,
        "mcp_install": mcp_install,
        "mcp_uninstall": mcp_uninstall,
        "mcp_list": mcp_list,
        "mcp_recommend": mcp_recommend,
        "mcp_start": mcp_start,
        "mcp_stop": mcp_stop,
    }
