from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse, ToolCall
from breadmind.tools.registry import ToolRegistry
from breadmind.core.safety import SafetyGuard, SafetyResult

if TYPE_CHECKING:
    from breadmind.memory.working import WorkingMemory

logger = logging.getLogger(__name__)


class CoreAgent:
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        system_prompt: str = "You are BreadMind, an AI infrastructure agent.",
        max_turns: int = 10,
        working_memory: WorkingMemory | None = None,
        tool_timeout: int = 30,
        chat_timeout: int = 120,
    ):
        self._provider = provider
        self._tools = tool_registry
        self._guard = safety_guard
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._working_memory = working_memory
        self._tool_timeout = tool_timeout
        self._chat_timeout = chat_timeout
        self._total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    def get_usage(self) -> dict[str, int]:
        return dict(self._total_usage)

    def _accumulate_usage(self, response: LLMResponse) -> None:
        if response.usage:
            self._total_usage["input_tokens"] += response.usage.input_tokens
            self._total_usage["output_tokens"] += response.usage.output_tokens

    async def handle_message(self, message: str, user: str, channel: str) -> str:
        session_id = f"{user}:{channel}"

        # Build initial messages
        system_msg = LLMMessage(role="system", content=self._system_prompt)
        user_msg = LLMMessage(role="user", content=message)

        if self._working_memory is not None:
            session = self._working_memory.get_or_create_session(
                session_id, user=user, channel=channel,
            )
            previous_messages = list(session.messages)
            messages = [system_msg] + previous_messages + [user_msg]
            # Save the user message to memory
            self._working_memory.add_message(session_id, user_msg)
        else:
            messages = [system_msg, user_msg]

        tools = self._tools.get_all_definitions()

        for turn in range(self._max_turns):
            try:
                response = await asyncio.wait_for(
                    self._provider.chat(messages=messages, tools=tools or None),
                    timeout=self._chat_timeout,
                )
            except asyncio.TimeoutError:
                return "요청 시간이 초과되었습니다."
            except Exception:
                logger.exception("LLM provider error")
                return "서비스 오류가 발생했습니다."

            self._accumulate_usage(response)

            if not response.has_tool_calls:
                final_content = response.content or ""
                if self._working_memory is not None:
                    self._working_memory.add_message(
                        session_id,
                        LLMMessage(role="assistant", content=final_content),
                    )
                return final_content

            # Process tool calls — collect tasks for parallel execution
            # First, add the assistant message with all tool calls
            assistant_msg = LLMMessage(
                role="assistant", content=response.content, tool_calls=response.tool_calls,
            )
            messages.append(assistant_msg)
            if self._working_memory is not None:
                self._working_memory.add_message(session_id, assistant_msg)

            # Categorize tool calls
            executable_calls: list[ToolCall] = []
            for tc in response.tool_calls:
                safety = self._guard.check(tc.name, tc.arguments, user=user, channel=channel)

                if safety == SafetyResult.DENY:
                    tool_msg = LLMMessage(
                        role="tool",
                        content=f"[success=False] BLOCKED: {tc.name} is in the blacklist.",
                        tool_call_id=tc.id, name=tc.name,
                    )
                    messages.append(tool_msg)
                    if self._working_memory is not None:
                        self._working_memory.add_message(session_id, tool_msg)
                    continue

                if safety == SafetyResult.REQUIRE_APPROVAL:
                    tool_msg = LLMMessage(
                        role="tool",
                        content=f"[success=False] PENDING_APPROVAL: {tc.name} requires user approval. Inform the user.",
                        tool_call_id=tc.id, name=tc.name,
                    )
                    messages.append(tool_msg)
                    if self._working_memory is not None:
                        self._working_memory.add_message(session_id, tool_msg)
                    continue

                # Check cooldown
                cooldown_target = f"{user}:{channel}"
                if not self._guard.check_cooldown(cooldown_target, tc.name):
                    tool_msg = LLMMessage(
                        role="tool",
                        content=f"[success=False] COOLDOWN: {tc.name} is in cooldown. Please wait before retrying.",
                        tool_call_id=tc.id, name=tc.name,
                    )
                    messages.append(tool_msg)
                    if self._working_memory is not None:
                        self._working_memory.add_message(session_id, tool_msg)
                    continue

                executable_calls.append(tc)

            # Execute allowed tool calls in parallel
            if executable_calls:
                async def _execute_one(tc: ToolCall) -> tuple[ToolCall, str]:
                    try:
                        result = await asyncio.wait_for(
                            self._tools.execute(tc.name, tc.arguments),
                            timeout=self._tool_timeout,
                        )
                        prefix = f"[success={result.success}]"
                        return tc, f"{prefix} {result.output}"
                    except asyncio.TimeoutError:
                        return tc, f"[success=False] Tool execution timed out after {self._tool_timeout}s."
                    except Exception as e:
                        logger.exception(f"Tool execution error: {tc.name}")
                        return tc, f"[success=False] Tool execution error: {e}"

                results = await asyncio.gather(
                    *[_execute_one(tc) for tc in executable_calls]
                )

                for tc, output in results:
                    tool_msg = LLMMessage(
                        role="tool", content=output,
                        tool_call_id=tc.id, name=tc.name,
                    )
                    messages.append(tool_msg)
                    if self._working_memory is not None:
                        self._working_memory.add_message(session_id, tool_msg)

        return "Maximum tool call turns reached. Please try a simpler request."
