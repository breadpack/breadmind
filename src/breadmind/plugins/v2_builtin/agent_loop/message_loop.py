from __future__ import annotations
import uuid
from typing import Any
from breadmind.core.protocols import (
    AgentContext, AgentProtocol, AgentResponse, ExecutionContext,
    LLMResponse, Message, PromptBlock, PromptContext, ProviderProtocol,
    ToolCall, ToolCallRequest,
)
from breadmind.plugins.v2_builtin.safety.guard import SafetyGuard


class MessageLoopAgent:
    """기본 메시지 루프 에이전트."""

    def __init__(self, provider: ProviderProtocol, prompt_builder: Any,
                 tool_registry: Any, safety_guard: SafetyGuard,
                 max_turns: int = 10, memory: Any | None = None,
                 prompt_context: PromptContext | None = None) -> None:
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._tool_registry = tool_registry
        self._safety = safety_guard
        self._max_turns = max_turns
        self._memory = memory
        self._prompt_context = prompt_context or PromptContext()
        self._agent_id = f"agent_{uuid.uuid4().hex[:8]}"

    @property
    def agent_id(self) -> str:
        return self._agent_id

    async def handle_message(self, message: str, ctx: AgentContext) -> AgentResponse:
        blocks = self._prompt_builder.build(self._prompt_context)
        system_content = "\n\n".join(b.content for b in blocks if b.content)

        messages: list[Message] = [
            Message(role="system", content=system_content),
            Message(role="user", content=message),
        ]

        tool_schemas = self._tool_registry.get_schemas()
        tools = [
            {"name": s.name, "description": s.definition.description, "input_schema": s.definition.parameters}
            for s in tool_schemas if s.definition
        ] or None

        total_tool_calls = 0
        total_tokens = 0

        for _ in range(self._max_turns):
            response: LLMResponse = await self._provider.chat(messages, tools)
            total_tokens += response.usage.total_tokens

            if not response.has_tool_calls:
                return AgentResponse(
                    content=response.content or "",
                    tool_calls_count=total_tool_calls,
                    tokens_used=total_tokens,
                )

            # Tool call processing
            assistant_msg = Message(
                role="assistant", content=response.content,
                tool_calls=response.tool_calls,
            )
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                total_tool_calls += 1
                exec_ctx = ExecutionContext(
                    user=ctx.user, channel=ctx.channel,
                    session_id=ctx.session_id, autonomy="auto",
                )

                verdict = self._safety.check(tc.name, tc.arguments)
                if not verdict.allowed:
                    messages.append(Message(
                        role="tool", content=f"Blocked: {verdict.reason}",
                        tool_call_id=tc.id,
                    ))
                    continue

                tool_call = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                result = await self._tool_registry.execute(tool_call, exec_ctx)
                messages.append(Message(
                    role="tool",
                    content=result.output if result.success else f"Error: {result.error}",
                    tool_call_id=tc.id,
                ))

        return AgentResponse(
            content="Max turns reached.",
            tool_calls_count=total_tool_calls,
            tokens_used=total_tokens,
        )

    async def spawn(self, prompt: str, tools: list[str] | None = None,
                    isolation: str | None = None) -> AgentProtocol:
        raise NotImplementedError("Spawner plugin required")

    async def send_message(self, target: str, message: str) -> str:
        raise NotImplementedError("Send message not implemented in base loop")

    def set_role(self, role: str) -> None:
        self._prompt_context.role = role
