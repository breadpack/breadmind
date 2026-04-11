"""Spawn/SendMessage 도구: LLM이 서브에이전트를 생성하고 메시지를 전달."""
from __future__ import annotations

from typing import TYPE_CHECKING

from breadmind.core.protocols import AgentContext, ToolDefinition

if TYPE_CHECKING:
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent

SPAWN_TOOL_DEFINITION = ToolDefinition(
    name="spawn_agent",
    description="Spawn a sub-agent to handle a specific task independently. Optionally creates a new role dynamically if system_prompt is provided.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Task description for the sub-agent",
            },
            "role": {
                "type": "string",
                "description": "Optional role hint (e.g., 'k8s_expert')",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for a new role (only used when creating a new role)",
            },
            "provider": {
                "type": "string",
                "description": "LLM provider for the new role (e.g. 'claude', 'gemini')",
            },
            "model": {
                "type": "string",
                "description": "Model name for the new role",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names available to the sub-agent",
            },
            "persistent": {
                "type": "boolean",
                "description": "If true, the role is saved permanently. Default false for agent-created roles.",
            },
        },
        "required": ["prompt"],
    },
    readonly=False,
)

SEND_MESSAGE_TOOL_DEFINITION = ToolDefinition(
    name="send_message",
    description="Send a follow-up message to a running sub-agent.",
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Agent ID to send message to",
            },
            "message": {
                "type": "string",
                "description": "Message content",
            },
        },
        "required": ["target", "message"],
    },
    readonly=False,
)


class SpawnToolExecutor:
    """spawn_agent / send_message 도구 실행기."""

    def __init__(
        self,
        agent: MessageLoopAgent,
        role_registry: object | None = None,
        db: object | None = None,
    ) -> None:
        self._agent = agent
        self._role_registry = role_registry
        self._db = db

    async def execute_spawn(
        self,
        prompt: str,
        role: str | None = None,
        system_prompt: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        persistent: bool = False,
    ) -> str:
        """서브에이전트를 spawn하고 초기 프롬프트를 실행하여 결과를 반환."""
        if role and system_prompt and self._role_registry:
            if self._role_registry.get(role) is None:
                from breadmind.core.role_registry import RoleDefinition
                new_role = RoleDefinition(
                    name=role,
                    system_prompt=system_prompt,
                    provider=provider or "",
                    model=model or "",
                    tools=tools or [],
                    tool_mode="whitelist" if tools else "blacklist",
                    persistent=persistent,
                    created_by="agent",
                )
                await self._role_registry.register(new_role, db=self._db if persistent else None)
        child = await self._agent.spawn(prompt)
        if role:
            child.set_role(role)
        ctx = AgentContext(
            user="system",
            channel="internal",
            session_id=f"spawn_{child.agent_id}",
        )
        response = await child.handle_message(prompt, ctx)
        return f"[Agent {child.agent_id}] {response.content}"

    async def execute_send(self, target: str, message: str) -> str:
        """실행 중인 자식 에이전트에 후속 메시지를 전송."""
        return await self._agent.send_message(target, message)
