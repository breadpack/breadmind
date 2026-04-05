"""Agent orchestration tools: task delegation and swarm role management."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from breadmind.constants import THINK_BUDGET_SMALL
from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


class AgentToolsPlugin(BaseToolPlugin):
    """Plugin providing delegate_tasks and swarm_role tools."""

    name = "agent-tools"
    version = "0.1.0"

    def __init__(self) -> None:
        self._llm_provider: Any | None = None
        self._tool_registry: Any | None = None
        self._swarm_manager: Any | None = None
        self._swarm_db: Any | None = None

    async def setup(self, container: Any) -> None:
        """Resolve optional dependencies from the service container."""
        self._llm_provider = container.get_optional("llm_provider")
        self._tool_registry = container.get_optional("tool_registry")
        self._swarm_manager = container.get_optional("swarm_manager")
        self._swarm_db = container.get_optional("swarm_db")

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @tool(
        description=(
            "Manage Agent Swarm roles. action: 'list', 'add', 'update', or 'remove'. "
            "For add/update, provide name, system_prompt, and description."
        )
    )
    async def swarm_role(
        self,
        action: str,
        name: str = "",
        system_prompt: str = "",
        description: str = "",
    ) -> str:
        if self._swarm_manager is None:
            return "Swarm manager not configured."

        if action == "list":
            roles = self._swarm_manager.get_available_roles()
            lines = [f"- **{r['role']}**: {r['description']}" for r in roles]
            return f"Available roles ({len(roles)}):\n" + "\n".join(lines)

        elif action == "add":
            if not name or not system_prompt:
                return "Error: name and system_prompt are required for adding a role."
            name = name.strip().lower().replace(" ", "_")
            self._swarm_manager.add_role(name, system_prompt, description or name)
            if self._swarm_db:
                try:
                    await self._swarm_db.set_setting(
                        "swarm_roles", self._swarm_manager.export_roles()
                    )
                except Exception:
                    pass
            return f"Role '{name}' added successfully."

        elif action == "update":
            if not name:
                return "Error: name is required for updating a role."
            self._swarm_manager.update_role(
                name, system_prompt=system_prompt, description=description
            )
            if self._swarm_db:
                try:
                    await self._swarm_db.set_setting(
                        "swarm_roles", self._swarm_manager.export_roles()
                    )
                except Exception:
                    pass
            return f"Role '{name}' updated."

        elif action == "remove":
            if not name:
                return "Error: name is required for removing a role."
            removed = self._swarm_manager.remove_role(name)
            if not removed:
                return f"Role '{name}' not found."
            if self._swarm_db:
                try:
                    await self._swarm_db.set_setting(
                        "swarm_roles", self._swarm_manager.export_roles()
                    )
                except Exception:
                    pass
            return f"Role '{name}' removed."

        return f"Unknown action: {action}. Use list, add, update, or remove."

    @tool(
        description=(
            "Delegate multiple independent tasks to parallel subagents for faster execution. "
            "Use when the user's request contains 2+ independent sub-tasks that can run simultaneously. "
            "Each task gets its own subagent. Results are collected and returned together. "
            "Example: '\uc11c\ubc84 \uc0c1\ud0dc \ud655\uc778\ud558\uace0 \ub0b4\uc77c \uc77c\uc815\ub3c4 \ubcf4\uc5ec\uc918' \u2192 2 parallel tasks. "
            "Pass tasks as a JSON array of strings, "
            'e.g. ["\uc11c\ubc84 \uc0c1\ud0dc \ud655\uc778", "\ub0b4\uc77c \uc77c\uc815 \uc870\ud68c"].'
        )
    )
    async def delegate_tasks(
        self,
        tasks: str,
        _agent: object = None,
        _provider: object = None,
        _registry: object = None,
    ) -> str:
        """Delegate tasks to parallel subagents."""
        import json as _json

        # Parse tasks (JSON array or comma-separated)
        try:
            task_list = _json.loads(tasks)
        except (_json.JSONDecodeError, TypeError):
            task_list = [t.strip() for t in tasks.split(",") if t.strip()]

        if not isinstance(task_list, list):
            task_list = [str(task_list)]

        if len(task_list) < 2:
            return (
                "\ub2e8\uc77c \uc791\uc5c5\uc740 \uc9c1\uc811 \ucc98\ub9ac\ud569\ub2c8\ub2e4. "
                "delegate_tasks\ub294 2\uac1c \uc774\uc0c1\uc758 \ub3c5\ub9bd \uc791\uc5c5\uc5d0 \uc0ac\uc6a9\ud558\uc138\uc694."
            )

        provider = self._llm_provider
        registry = self._tool_registry

        if not provider or not registry:
            return "\uc11c\ube0c\uc5d0\uc774\uc804\ud2b8\ub97c \uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. (provider/registry not injected)"

        async def run_subtask(task_desc: str, idx: int) -> dict:
            try:
                from breadmind.llm.base import LLMMessage as _LLMMessage

                sub_messages = [
                    _LLMMessage(
                        role="system",
                        content=(
                            "You are a focused subagent of BreadMind. "
                            "Complete the given task concisely. Respond in Korean."
                        ),
                    ),
                    _LLMMessage(role="user", content=task_desc),
                ]

                # Get tool definitions from registry
                all_tools = registry.get_all_definitions() if registry else []
                sub_tools = all_tools[:20]  # Limit tools for subagent

                response = await provider.chat(
                    messages=sub_messages,
                    tools=sub_tools or None,
                    think_budget=3072,
                )

                # Handle tool calls in a simple loop (max 3 turns)
                for _ in range(3):
                    if not response.tool_calls:
                        break
                    for tc in response.tool_calls:
                        try:
                            result = await registry.execute(tc.name, tc.arguments)
                            sub_messages.append(
                                _LLMMessage(
                                    role="tool",
                                    content=f"[success={result.success}] {result.output[:2000]}",
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                )
                            )
                        except Exception as e:
                            sub_messages.append(
                                _LLMMessage(
                                    role="tool",
                                    content=f"[success=False] Error: {e}",
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                )
                            )
                    # Add assistant message with tool_calls for context
                    sub_messages.append(
                        _LLMMessage(
                            role="assistant",
                            content=response.content,
                            tool_calls=response.tool_calls,
                        )
                    )
                    response = await provider.chat(
                        messages=sub_messages,
                        tools=sub_tools or None,
                        think_budget=THINK_BUDGET_SMALL,
                    )

                return {
                    "task": task_desc,
                    "result": response.content or "\uc644\ub8cc",
                    "success": True,
                }
            except Exception as e:
                logger.warning("Subagent task %d failed: %s", idx, e)
                return {"task": task_desc, "result": f"\uc2e4\ud328: {e}", "success": False}

        # Run all tasks in parallel
        results = await asyncio.gather(
            *[run_subtask(task, i) for i, task in enumerate(task_list)]
        )

        # Format results
        lines = [f"## \ubcd1\ub82c \ucc98\ub9ac \uacb0\uacfc ({len(results)}\uac1c \uc791\uc5c5)\n"]
        for i, r in enumerate(results, 1):
            status = "SUCCESS" if r["success"] else "FAILED"
            lines.append(f"### [{status}] \uc791\uc5c5 {i}: {r['task']}\n{r['result']}\n")

        return "\n".join(lines)

    def get_tools(self) -> list[Callable]:
        tools = [self.delegate_tasks, self.swarm_role]

        # Remove internal injection params from delegate_tasks schema
        # so the LLM only sees 'tasks'
        # Note: 'self' is already skipped by the @tool decorator
        defn = self.delegate_tasks._tool_definition
        for internal_param in ("_agent", "_provider", "_registry"):
            defn.parameters.get("properties", {}).pop(internal_param, None)
            if internal_param in defn.parameters.get("required", []):
                defn.parameters["required"].remove(internal_param)

        return tools
