"""Dynamic role definitions with DB persistence for orchestrator subagents."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

logger = __import__("logging").getLogger(__name__)


@dataclass
class RoleDefinition:
    name: str
    domain: str = "general"
    task_type: str = "general"
    system_prompt: str = ""
    description: str = ""
    provider: str = ""            # LLM provider (empty = system default)
    model: str = ""               # Model name (empty = system default)
    tool_mode: str = "whitelist"  # "whitelist" | "blacklist"
    tools: list[str] = field(default_factory=list)
    persistent: bool = True       # False = memory-only, auto-cleaned
    created_by: str = "user"      # "user" | "agent"
    max_turns: int = 5

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "domain": self.domain,
            "task_type": self.task_type,
            "system_prompt": self.system_prompt,
            "description": self.description,
            "provider": self.provider,
            "model": self.model,
            "tool_mode": self.tool_mode,
            "tools": self.tools,
            "persistent": self.persistent,
            "created_by": self.created_by,
            "max_turns": self.max_turns,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoleDefinition":
        tools = data.get("tools", [])
        if isinstance(tools, str):
            tools = json.loads(tools)
        return cls(
            name=data["name"],
            domain=data.get("domain", "general"),
            task_type=data.get("task_type", "general"),
            system_prompt=data.get("system_prompt", ""),
            description=data.get("description", ""),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            tool_mode=data.get("tool_mode", "whitelist"),
            tools=tools,
            persistent=data.get("persistent", True),
            created_by=data.get("created_by", "user"),
            max_turns=data.get("max_turns", 5),
        )


class RoleRegistry:
    """Registry of subagent role definitions backed by DB persistence."""

    def __init__(self) -> None:
        self._roles: dict[str, RoleDefinition] = {}

    # ------------------------------------------------------------------
    # DB I/O
    # ------------------------------------------------------------------

    async def load_from_db(self, db) -> int:
        """Load all roles from the subagent_roles table. Returns the count loaded."""
        async with db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM subagent_roles")
        count = 0
        for row in rows:
            try:
                role = RoleDefinition.from_dict(dict(row))
                self._roles[role.name] = role
                count += 1
            except Exception:
                logger.exception("Failed to load role from DB row: %s", dict(row))
        logger.debug("Loaded %d roles from DB", count)
        return count

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def register(self, role: RoleDefinition, db=None) -> None:
        """Add role to memory; if persistent=True and db provided, UPSERT to DB."""
        self._roles[role.name] = role
        logger.debug("Registered role: %s (persistent=%s)", role.name, role.persistent)

        if role.persistent and db is not None:
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO subagent_roles
                        (name, domain, task_type, system_prompt, description,
                         provider, model, tool_mode, tools, persistent,
                         created_by, max_turns)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (name) DO UPDATE SET
                        domain        = EXCLUDED.domain,
                        task_type     = EXCLUDED.task_type,
                        system_prompt = EXCLUDED.system_prompt,
                        description   = EXCLUDED.description,
                        provider      = EXCLUDED.provider,
                        model         = EXCLUDED.model,
                        tool_mode     = EXCLUDED.tool_mode,
                        tools         = EXCLUDED.tools,
                        persistent    = EXCLUDED.persistent,
                        created_by    = EXCLUDED.created_by,
                        max_turns     = EXCLUDED.max_turns
                    """,
                    role.name,
                    role.domain,
                    role.task_type,
                    role.system_prompt,
                    role.description,
                    role.provider,
                    role.model,
                    role.tool_mode,
                    json.dumps(role.tools),
                    role.persistent,
                    role.created_by,
                    role.max_turns,
                )

    async def remove(self, name: str, db=None) -> bool:
        """Remove a role by name. Returns True if removed, False if not found."""
        role = self._roles.pop(name, None)
        if role is None:
            return False

        logger.debug("Removed role: %s", name)

        if role.persistent and db is not None:
            async with db.acquire() as conn:
                await conn.execute(
                    "DELETE FROM subagent_roles WHERE name = $1", name
                )

        return True

    def get(self, name: str) -> RoleDefinition | None:
        """Return a role by name, or None if not found."""
        return self._roles.get(name)

    def list_roles(self) -> list[RoleDefinition]:
        """Return all registered roles."""
        return list(self._roles.values())

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def get_tools(self, role_name: str) -> tuple[str, list[str]]:
        """Return (tool_mode, tool_list) for a role.

        Returns ("whitelist", []) for unknown roles.
        """
        role = self._roles.get(role_name)
        if role is None:
            return ("whitelist", [])
        return (role.tool_mode, list(role.tools))

    def get_prompt(self, role_name: str) -> str:
        """Return the system prompt for a role, or an empty string if not found."""
        role = self._roles.get(role_name)
        return role.system_prompt if role is not None else ""

    def get_model_config(self, role_name: str) -> tuple[str, str]:
        """Return (provider, model) for a role. Empty strings for unknown roles."""
        role = self._roles.get(role_name)
        if role is None:
            return ("", "")
        return (role.provider, role.model)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def cleanup_transient(self) -> list[str]:
        """Remove all persistent=False roles. Returns list of removed names."""
        to_remove = [name for name, role in self._roles.items() if not role.persistent]
        for name in to_remove:
            del self._roles[name]
            logger.debug("Cleaned up transient role: %s", name)
        return to_remove

    # ------------------------------------------------------------------
    # Summary for Planner
    # ------------------------------------------------------------------

    def list_role_summaries(self) -> str:
        """Return a formatted string listing all roles, suitable for a Planner prompt."""
        if not self._roles:
            return (
                "No subagent roles defined. The agent can create roles dynamically "
                "using spawn_agent."
            )

        lines: list[str] = ["Available subagent roles:"]
        for role in self._roles.values():
            tool_preview = ", ".join(role.tools[:5])
            if len(role.tools) > 5:
                tool_preview += f", ... (+{len(role.tools) - 5} more)"
            desc = role.description or role.system_prompt[:80]
            lines.append(
                f"  - {role.name} [{role.domain}/{role.task_type}]: {desc}"
                + (f" | tools: {tool_preview}" if tool_preview else "")
            )
        return "\n".join(lines)
