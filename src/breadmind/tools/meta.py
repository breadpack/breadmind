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

    @tool(description="Install an AI skill from skills.sh or a GitHub repository. Provide the slug in format 'owner/repo/skill-name' (e.g., 'anthropics/skills/frontend-design'). The skill's prompt template will be downloaded and stored for automatic use in relevant conversations.")
    async def skill_install(slug: str) -> str:
        if skill_store is None:
            return "SkillStore not available."
        import aiohttp
        parts = slug.strip().split("/")
        if len(parts) < 3:
            return f"Error: Invalid slug format '{slug}'. Expected 'owner/repo/skill-name'."
        owner = parts[0]
        repo = parts[1]
        skill_name = "/".join(parts[2:])

        # Try multiple path patterns
        paths = [
            f"skills/{skill_name}/SKILL.md",
            f"{skill_name}/SKILL.md",
            f"skills/{skill_name}.md",
        ]
        content = None
        async with aiohttp.ClientSession() as session:
            for path in paths:
                url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            break
                except Exception:
                    continue

        if not content:
            return f"Error: Could not find SKILL.md for '{slug}'. Tried paths: {', '.join(paths)}"

        # Parse YAML frontmatter
        description = ""
        prompt_template = content
        trigger_keywords = []
        if content.startswith("---"):
            parts_md = content.split("---", 2)
            if len(parts_md) >= 3:
                import yaml
                try:
                    meta = yaml.safe_load(parts_md[1])
                    if isinstance(meta, dict):
                        description = meta.get("description", "")
                        skill_name_from_meta = meta.get("name", skill_name)
                        if skill_name_from_meta:
                            skill_name = skill_name_from_meta
                except Exception:
                    pass
                prompt_template = parts_md[2].strip()

        # Extract keywords from description and name
        import re
        words = re.findall(r'[a-zA-Z0-9_-]+', f"{skill_name} {description}".lower())
        trigger_keywords = list(set(w for w in words if len(w) > 2))[:15]

        # Store in SkillStore
        try:
            existing = await skill_store.get_skill(skill_name)
            if existing:
                await skill_store.update_skill(
                    skill_name,
                    description=description,
                    prompt_template=prompt_template,
                    trigger_keywords=trigger_keywords,
                )
                action = "Updated"
            else:
                await skill_store.add_skill(
                    name=skill_name,
                    description=description,
                    prompt_template=prompt_template,
                    steps=[],
                    trigger_keywords=trigger_keywords,
                    source=f"skills.sh:{slug}",
                )
                action = "Installed"

            # Persist to DB
            await skill_store.flush_to_db()

            return (
                f"{action} skill '{skill_name}' from {owner}/{repo}.\n"
                f"Description: {description[:200]}\n"
                f"Keywords: {', '.join(trigger_keywords[:10])}\n"
                f"The skill will be automatically applied when relevant topics are discussed."
            )
        except Exception as e:
            return f"Error installing skill: {e}"

    @tool(description="Uninstall a previously installed AI skill by name.")
    async def skill_uninstall(name: str) -> str:
        if skill_store is None:
            return "SkillStore not available."
        removed = await skill_store.remove_skill(name)
        if removed:
            await skill_store.flush_to_db()
            return f"Skill '{name}' uninstalled."
        return f"Skill '{name}' not found."

    return {
        "skill_manage": skill_manage,
        "performance_report": performance_report,
        "skill_install": skill_install,
        "skill_uninstall": skill_uninstall,
    }


def create_memory_tools(
    episodic_memory=None,
    profiler=None,
    smart_retriever=None,
) -> dict:

    @tool(description="Save important information for future conversations. Use when the user asks to remember something, states a preference, or shares a fact worth keeping. category: 'preference', 'fact', 'instruction', or 'incident'.")
    async def memory_save(content: str, category: str = "fact") -> str:
        if episodic_memory is None:
            return "Memory system not available."
        try:
            valid_categories = {"preference", "fact", "instruction", "incident"}
            if category not in valid_categories:
                category = "fact"

            # Store as episodic note with structured tags
            keywords = content.lower().split()[:10]  # Simple keyword extraction
            note = await episodic_memory.add_note(
                content=content,
                keywords=keywords,
                tags=[f"memory:{category}", "explicit_memory"],
                context_description=f"User-requested memory ({category})",
            )
            # Pin explicit user memories — they should never decay
            episodic_memory.pin_note(note)

            # Also store as user preference if applicable
            if category == "preference" and profiler:
                from breadmind.memory.profiler import UserPreference
                await profiler.add_preference("default", UserPreference(
                    category=content[:50], description=content,
                ))

            # Index in SmartRetriever if available
            if smart_retriever:
                try:
                    await smart_retriever.index_task_result(
                        role="user", task_desc=f"memory_{category}",
                        result_summary=content, success=True,
                    )
                except Exception:
                    pass

            return f"Remembered: {content[:100]}{'...' if len(content) > 100 else ''}"
        except Exception as e:
            return f"Failed to save memory: {e}"

    @tool(description="Search your long-term memory for previously saved information. Use at conversation start or when context from past interactions would be helpful.")
    async def memory_search(query: str, limit: int = 5) -> str:
        if episodic_memory is None:
            return "Memory system not available."
        try:
            results = []

            # Try smart retriever first (vector + KG)
            if smart_retriever:
                try:
                    context_items = await smart_retriever.retrieve_context(query, token_budget=1500, limit=limit)
                    for item in context_items:
                        results.append(f"- [{item.source}] {item.content}")
                except Exception:
                    pass

            # Fallback to keyword search
            if not results:
                keywords = query.lower().split()[:5]
                notes = await episodic_memory.search_by_keywords(keywords, limit=limit)
                for note in notes:
                    results.append(f"- {note.content}")

            if not results:
                return "No relevant memories found."
            return "Memories found:\n" + "\n".join(results)
        except Exception as e:
            return f"Memory search failed: {e}"

    @tool(description="Delete a previously saved memory by its content. Use when the user asks to forget something or when information is outdated.")
    async def memory_delete(content_match: str) -> str:
        if episodic_memory is None:
            return "Memory system not available."
        try:
            # Search for matching notes
            keywords = content_match.lower().split()[:5]
            notes = await episodic_memory.search_by_keywords(keywords, limit=5)

            deleted = 0
            for note in notes:
                if content_match.lower() in note.content.lower():
                    await episodic_memory.delete_note(note.id)
                    deleted += 1

            if deleted == 0:
                return f"No matching memories found for: {content_match}"
            return f"Deleted {deleted} memory/memories matching: {content_match[:50]}"
        except Exception as e:
            return f"Failed to delete memory: {e}"

    return {
        "memory_save": memory_save,
        "memory_search": memory_search,
        "memory_delete": memory_delete,
    }
