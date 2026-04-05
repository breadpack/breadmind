"""SubAgent: individual task execution unit with its own LLM loop."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

from breadmind.llm.base import LLMProvider, LLMMessage, ToolCall

logger = logging.getLogger("breadmind.subagent")


@dataclass
class SubAgentResult:
    task_id: str
    success: bool
    output: str
    turns_used: int = 0
    error: str = ""


class SubAgent:
    """Executes a single task with a dedicated LLM loop and role-specific tools."""

    def __init__(
        self,
        task_id: str,
        description: str,
        role: str,
        provider: LLMProvider,
        tools: list[dict],
        system_prompt: str,
        max_turns: int = 5,
        tool_executor: Callable[..., Awaitable] | None = None,
        model_override: str | None = None,
    ) -> None:
        self._task_id = task_id
        self._description = description
        self._role = role
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._tool_executor = tool_executor
        self._model_override = model_override

    async def run(self, context: dict[str, str] | None = None) -> SubAgentResult:
        """Execute the task and return the result."""
        messages = self._build_messages(context or {})

        for turn in range(self._max_turns):
            try:
                response = await self._provider.chat(
                    messages=messages,
                    tools=self._tools or None,
                    model=self._model_override,
                )
            except Exception as e:
                logger.error("SubAgent %s LLM error: %s", self._task_id, e)
                return SubAgentResult(
                    task_id=self._task_id, success=False,
                    output=f"[success=False] LLM error: {e}",
                    turns_used=turn + 1, error=str(e),
                )

            if not response.has_tool_calls:
                return SubAgentResult(
                    task_id=self._task_id, success=True,
                    output=response.content or "",
                    turns_used=turn + 1,
                )

            # Process tool calls
            messages.append(LLMMessage(
                role="assistant", content=response.content,
                tool_calls=response.tool_calls,
            ))

            for tc in response.tool_calls:
                tool_output = await self._execute_tool(tc)
                messages.append(LLMMessage(
                    role="tool", content=tool_output,
                    tool_call_id=tc.id, name=tc.name,
                ))

        # Max turns exceeded
        last_content = messages[-1].content or "" if messages else ""
        return SubAgentResult(
            task_id=self._task_id, success=False,
            output=f"[success=False] Max turns ({self._max_turns}) exceeded. Last output: {last_content}",
            turns_used=self._max_turns,
        )

    def _build_messages(self, context: dict[str, str]) -> list[LLMMessage]:
        msgs = [LLMMessage(role="system", content=self._system_prompt)]
        if context:
            context_text = "\n".join(
                f"[Prior result from {tid}]: {output}" for tid, output in context.items()
            )
            msgs.append(LLMMessage(
                role="system",
                content=f"Context from prior tasks:\n{context_text}",
            ))
        msgs.append(LLMMessage(role="user", content=self._description))
        return msgs

    async def _execute_tool(self, tc: ToolCall) -> str:
        if self._tool_executor is None:
            return f"[success=False] No tool executor available for {tc.name}"
        try:
            result = await self._tool_executor(tc.name, tc.arguments)
            prefix = "[success=True]" if result.success else "[success=False]"
            output = str(result.output)[:50000]
            return f"{prefix} {output}"
        except Exception as e:
            return f"[success=False] Tool error: {e}"
