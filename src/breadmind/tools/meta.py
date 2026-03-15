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


def create_expansion_tools(
    skill_store=None,
    tracker=None,
) -> dict:

    @tool(description="Manage reusable skills. action: 'list', 'add', 'update', 'remove'. For add: provide name, description, prompt_template, trigger_keywords (comma-separated).")
    async def skill_manage(
        action: str, name: str = "", description: str = "",
        prompt_template: str = "", trigger_keywords: str = "",
    ) -> str:
        if skill_store is None:
            return "SkillStore not available."
        if action == "list":
            skills = await skill_store.list_skills()
            if not skills:
                return "No skills registered."
            lines = []
            for s in skills:
                lines.append(f"- **{s.name}** ({s.source}): {s.description}")
                lines.append(f"  Keywords: {', '.join(s.trigger_keywords)}")
                lines.append(f"  Usage: {s.usage_count} (success: {s.success_count})")
            return "\n".join(lines)
        if action == "add":
            if not name or not description:
                return "Error: name and description required."
            try:
                kws = [k.strip() for k in trigger_keywords.split(",") if k.strip()]
                skill = await skill_store.add_skill(name, description, prompt_template, [], kws, "manual")
                return f"Skill '{skill.name}' created."
            except ValueError as e:
                return f"Error: {e}"
        if action == "update":
            if not name:
                return "Error: name required."
            kwargs = {}
            if description:
                kwargs["description"] = description
            if prompt_template:
                kwargs["prompt_template"] = prompt_template
            if trigger_keywords:
                kwargs["trigger_keywords"] = [k.strip() for k in trigger_keywords.split(",")]
            try:
                await skill_store.update_skill(name, **kwargs)
                return f"Skill '{name}' updated."
            except ValueError as e:
                return f"Error: {e}"
        if action == "remove":
            if not name:
                return "Error: name required."
            removed = await skill_store.remove_skill(name)
            return f"Skill '{name}' removed." if removed else f"Skill '{name}' not found."
        return f"Unknown action: {action}. Use list, add, update, or remove."

    @tool(description="View performance stats for swarm roles. Optionally specify a role name for detailed stats.")
    async def performance_report(role: str = "") -> str:
        if tracker is None:
            return "PerformanceTracker not available."
        if role:
            stats = tracker.get_role_stats(role)
            if not stats:
                return f"No stats for role '{role}'."
            return (
                f"**{role}** — {stats.total_runs} runs, "
                f"{stats.success_rate:.0%} success rate, "
                f"avg {stats.avg_duration_ms:.0f}ms\n"
                f"Successes: {stats.successes}, Failures: {stats.failures}\n"
                f"Feedback entries: {len(stats.feedback_history)}"
            )
        all_stats = tracker.get_all_stats()
        if not all_stats:
            return "No performance data available."
        lines = []
        for name, stats in sorted(all_stats.items()):
            lines.append(f"- **{name}**: {stats.total_runs} runs, "
                f"{stats.success_rate:.0%} success, avg {stats.avg_duration_ms:.0f}ms")
        return "\n".join(lines)

    return {
        "skill_manage": skill_manage,
        "performance_report": performance_report,
    }
