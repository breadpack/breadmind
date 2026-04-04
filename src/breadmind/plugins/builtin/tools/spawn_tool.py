"""Spawn/SendMessage 도구: LLM이 서브에이전트를 생성하고 메시지를 전달."""
from __future__ import annotations

from typing import TYPE_CHECKING

from breadmind.core.protocols import AgentContext, ToolDefinition

if TYPE_CHECKING:
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent

SPAWN_TOOL_DEFINITION = ToolDefinition(
    name="spawn_agent",
    description="Spawn a sub-agent to handle a specific task independently.",
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

    def __init__(self, agent: MessageLoopAgent) -> None:
        self._agent = agent

    async def execute_spawn(self, prompt: str, role: str | None = None) -> str:
        """서브에이전트를 spawn하고 초기 프롬프트를 실행하여 결과를 반환."""
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
