"""Skills management plugin — manage, install, uninstall AI skills."""

from __future__ import annotations

from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool


class SkillsPlugin(BaseToolPlugin):
    name = "skills"
    version = "0.1.0"

    def __init__(self) -> None:
        self._skill_store: Any = None
        self._tracker: Any = None

    async def setup(self, container: Any) -> None:
        self._skill_store = container.get("skill_store")
        try:
            self._tracker = container.get("performance_tracker")
        except Exception:
            self._tracker = None

    def get_tools(self) -> list[Callable]:
        return [
            self.skill_manage,
            self.skill_install,
            self.skill_uninstall,
            self.performance_report,
        ]

    @tool(
        description=(
            "Manage reusable skills. action: 'list', 'add', 'update', 'remove'. "
            "For add: provide name, description, prompt_template, "
            "trigger_keywords (comma-separated)."
        )
    )
    async def skill_manage(
        self,
        action: str,
        name: str = "",
        description: str = "",
        prompt_template: str = "",
        trigger_keywords: str = "",
    ) -> str:
        if self._skill_store is None:
            return "SkillStore not available."
        if action == "list":
            skills = await self._skill_store.list_skills()
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
                skill = await self._skill_store.add_skill(
                    name, description, prompt_template, [], kws, "manual",
                )
                return f"Skill '{skill.name}' created."
            except ValueError as e:
                return f"Error: {e}"
        if action == "update":
            if not name:
                return "Error: name required."
            kwargs: dict[str, Any] = {}
            if description:
                kwargs["description"] = description
            if prompt_template:
                kwargs["prompt_template"] = prompt_template
            if trigger_keywords:
                kwargs["trigger_keywords"] = [
                    k.strip() for k in trigger_keywords.split(",")
                ]
            try:
                await self._skill_store.update_skill(name, **kwargs)
                return f"Skill '{name}' updated."
            except ValueError as e:
                return f"Error: {e}"
        if action == "remove":
            if not name:
                return "Error: name required."
            removed = await self._skill_store.remove_skill(name)
            return f"Skill '{name}' removed." if removed else f"Skill '{name}' not found."
        return f"Unknown action: {action}. Use list, add, update, or remove."

    @tool(
        description=(
            "Install an AI skill from skills.sh or a GitHub repository. "
            "Provide the slug in format 'owner/repo/skill-name' "
            "(e.g., 'anthropics/skills/frontend-design'). The skill's prompt "
            "template will be downloaded and stored for automatic use in "
            "relevant conversations."
        )
    )
    async def skill_install(self, slug: str) -> str:
        if self._skill_store is None:
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
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            break
                except Exception:
                    continue

        if not content:
            return (
                f"Error: Could not find SKILL.md for '{slug}'. "
                f"Tried paths: {', '.join(paths)}"
            )

        # Parse YAML frontmatter
        description = ""
        prompt_template = content
        trigger_keywords: list[str] = []
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

        words = re.findall(
            r"[a-zA-Z0-9_-]+", f"{skill_name} {description}".lower(),
        )
        trigger_keywords = list(set(w for w in words if len(w) > 2))[:15]

        # Store in SkillStore
        try:
            existing = await self._skill_store.get_skill(skill_name)
            if existing:
                await self._skill_store.update_skill(
                    skill_name,
                    description=description,
                    prompt_template=prompt_template,
                    trigger_keywords=trigger_keywords,
                )
                action = "Updated"
            else:
                await self._skill_store.add_skill(
                    name=skill_name,
                    description=description,
                    prompt_template=prompt_template,
                    steps=[],
                    trigger_keywords=trigger_keywords,
                    source=f"skills.sh:{slug}",
                )
                action = "Installed"

            # Persist to DB
            await self._skill_store.flush_to_db()

            return (
                f"{action} skill '{skill_name}' from {owner}/{repo}.\n"
                f"Description: {description[:200]}\n"
                f"Keywords: {', '.join(trigger_keywords[:10])}\n"
                f"The skill will be automatically applied when relevant "
                f"topics are discussed."
            )
        except Exception as e:
            return f"Error installing skill: {e}"

    @tool(description="Uninstall a previously installed AI skill by name.")
    async def skill_uninstall(self, name: str) -> str:
        if self._skill_store is None:
            return "SkillStore not available."
        removed = await self._skill_store.remove_skill(name)
        if removed:
            await self._skill_store.flush_to_db()
            return f"Skill '{name}' uninstalled."
        return f"Skill '{name}' not found."

    @tool(
        description=(
            "View performance stats for swarm roles. "
            "Optionally specify a role name for detailed stats."
        )
    )
    async def performance_report(self, role: str = "") -> str:
        if self._tracker is None:
            return "PerformanceTracker not available."
        if role:
            stats = self._tracker.get_role_stats(role)
            if not stats:
                return f"No stats for role '{role}'."
            return (
                f"**{role}** — {stats.total_runs} runs, "
                f"{stats.success_rate:.0%} success rate, "
                f"avg {stats.avg_duration_ms:.0f}ms\n"
                f"Successes: {stats.successes}, Failures: {stats.failures}\n"
                f"Feedback entries: {len(stats.feedback_history)}"
            )
        all_stats = self._tracker.get_all_stats()
        if not all_stats:
            return "No performance data available."
        lines = []
        for name, stats in sorted(all_stats.items()):
            lines.append(
                f"- **{name}**: {stats.total_runs} runs, "
                f"{stats.success_rate:.0%} success, "
                f"avg {stats.avg_duration_ms:.0f}ms"
            )
        return "\n".join(lines)
