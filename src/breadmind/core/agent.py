from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse, ToolCall
from breadmind.tools.registry import ToolRegistry, ToolResult
from breadmind.core.safety import SafetyGuard, SafetyResult
from breadmind.core.audit import AuditLogger

if TYPE_CHECKING:
    from breadmind.memory.working import WorkingMemory
    from breadmind.core.tool_gap import ToolGapDetector

logger = logging.getLogger("breadmind.agent")


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
        audit_logger: AuditLogger | None = None,
        summarizer: object | None = None,
        tool_gap_detector: ToolGapDetector | None = None,
        context_builder: object | None = None,
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
        self._audit_logger = audit_logger
        self._summarizer = summarizer
        self._tool_gap_detector = tool_gap_detector
        self._context_builder = context_builder
        self._pending_approvals: dict[str, dict] = {}

    async def update_provider(self, provider: LLMProvider):
        """Replace the LLM provider at runtime, closing the old one."""
        old = self._provider
        self._provider = provider
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass

    def update_timeouts(self, tool_timeout: int = None, chat_timeout: int = None):
        """Update timeout settings at runtime."""
        if tool_timeout is not None and tool_timeout >= 1:
            self._tool_timeout = tool_timeout
        if chat_timeout is not None and chat_timeout >= 1:
            self._chat_timeout = chat_timeout

    def get_timeouts(self) -> dict:
        return {
            "tool_timeout": self._tool_timeout,
            "chat_timeout": self._chat_timeout,
            "max_turns": self._max_turns,
        }

    def update_max_turns(self, max_turns: int):
        if max_turns >= 1:
            self._max_turns = max_turns

    def set_system_prompt(self, prompt: str):
        self._system_prompt = prompt

    def set_persona(self, persona: dict):
        from breadmind.config import build_system_prompt
        self._system_prompt = build_system_prompt(persona)

    def get_usage(self) -> dict[str, int]:
        return dict(self._total_usage)

    def _accumulate_usage(self, response: LLMResponse) -> None:
        if response.usage:
            self._total_usage["input_tokens"] += response.usage.input_tokens
            self._total_usage["output_tokens"] += response.usage.output_tokens

    def get_pending_approvals(self) -> list[dict]:
        """Return all pending approval requests."""
        return [
            {"approval_id": aid, **info}
            for aid, info in self._pending_approvals.items()
            if info.get("status") == "pending"
        ]

    async def approve_tool(self, approval_id: str) -> ToolResult:
        """Approve and execute a pending tool call."""
        approval = self._pending_approvals.get(approval_id)
        if approval is None or approval.get("status") != "pending":
            return ToolResult(success=False, output=f"No pending approval found: {approval_id}")

        approval["status"] = "approved"
        tool_name = approval["tool"]
        arguments = approval["args"]
        user = approval["user"]
        channel = approval["channel"]

        if self._audit_logger:
            self._audit_logger.log_approval_request(user, channel, tool_name, "approved")

        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._tools.execute(tool_name, arguments),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            result = ToolResult(success=False, output=f"Tool execution timed out after {self._tool_timeout}s.")
        except Exception as e:
            logger.exception(f"Tool execution error during approval: {tool_name}")
            result = ToolResult(success=False, output=f"Tool execution error: {e}")

        duration_ms = (time.monotonic() - t0) * 1000
        if self._audit_logger:
            self._audit_logger.log_tool_call(
                user, channel, tool_name, arguments,
                result.output, result.success, duration_ms,
            )

        return result

    def deny_tool(self, approval_id: str) -> None:
        """Deny a pending tool call."""
        approval = self._pending_approvals.get(approval_id)
        if approval is not None:
            user = approval.get("user", "")
            channel = approval.get("channel", "")
            tool_name = approval.get("tool", "")
            approval["status"] = "denied"
            if self._audit_logger:
                self._audit_logger.log_approval_request(user, channel, tool_name, "denied")

    async def handle_message(self, message: str, user: str, channel: str) -> str:
        session_id = f"{user}:{channel}"
        logger.info(json.dumps({"event": "session_start", "user": user, "channel": channel}))

        # Build initial messages
        system_msg = LLMMessage(role="system", content=self._system_prompt)
        user_msg = LLMMessage(role="user", content=message)

        if self._working_memory is not None:
            session = self._working_memory.get_or_create_session(
                session_id, user=user, channel=channel,
            )
            previous_messages = list(session.messages)
            logger.info(json.dumps({"event": "context_build", "session": session_id, "previous_msgs": len(previous_messages)}))
            messages = [system_msg] + previous_messages + [user_msg]
            # Save the user message to memory
            self._working_memory.add_message(session_id, user_msg)
        else:
            messages = [system_msg, user_msg]

        # Enrich context with episodic/semantic memory if available
        if self._context_builder:
            try:
                enrichment = await self._context_builder.build_context(session_id, message)
                # Extract only the enrichment system messages (not conversation history)
                context_msgs = [m for m in enrichment if m.role == "system" and m.content and m.content != self._system_prompt]
                if context_msgs:
                    # Insert context after system prompt, before conversation history
                    messages = [messages[0]] + context_msgs + messages[1:]
            except Exception as e:
                logger.warning(f"ContextBuilder enrichment failed: {e}")

        tools = self._tools.get_all_definitions()

        for turn in range(self._max_turns):
            # Apply conversation summarization if available
            chat_messages = messages
            if self._summarizer is not None and hasattr(self._summarizer, "summarize_if_needed"):
                try:
                    chat_messages = await self._summarizer.summarize_if_needed(messages, None)
                except Exception:
                    logger.exception("Summarizer error, using original messages")
                    chat_messages = messages

            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self._provider.chat(messages=chat_messages, tools=tools or None),
                    timeout=self._chat_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(json.dumps({"event": "llm_call", "status": "timeout", "user": user}))
                return "요청 시간이 초과되었습니다."
            except Exception:
                logger.exception("LLM provider error")
                return "서비스 오류가 발생했습니다."

            duration_ms = (time.monotonic() - t0) * 1000
            self._accumulate_usage(response)

            # Log LLM call
            model_name = getattr(self._provider, "model", "unknown")
            if not isinstance(model_name, str):
                model_name = "unknown"
            logger.info(json.dumps({
                "event": "llm_call",
                "model": model_name,
                "tokens": {
                    "input": response.usage.input_tokens if response.usage else 0,
                    "output": response.usage.output_tokens if response.usage else 0,
                },
                "duration_ms": round(duration_ms, 2),
            }))
            if self._audit_logger and response.usage:
                self._audit_logger.log_llm_call(
                    user, channel,
                    model=model_name,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_hit=getattr(response.usage, "cache_read_input_tokens", 0) > 0,
                    duration_ms=duration_ms,
                )

            if not response.has_tool_calls:
                final_content = response.content or ""
                if self._working_memory is not None:
                    self._working_memory.add_message(
                        session_id,
                        LLMMessage(role="assistant", content=final_content),
                    )
                logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel}))
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

                # Log safety decision
                if self._audit_logger:
                    self._audit_logger.log_safety_check(
                        user, channel, tc.name, safety.value,
                    )

                if safety == SafetyResult.DENY:
                    logger.info(json.dumps({"event": "safety_deny", "tool": tc.name, "user": user}))
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
                    approval_id = str(uuid.uuid4())
                    self._pending_approvals[approval_id] = {
                        "tool": tc.name, "args": tc.arguments,
                        "user": user, "channel": channel, "status": "pending",
                    }
                    tool_msg = LLMMessage(
                        role="tool",
                        content=f"[approval_required] Tool '{tc.name}' requires approval. Approval ID: {approval_id}. Ask the user to approve.",
                        tool_call_id=tc.id, name=tc.name,
                    )
                    messages.append(tool_msg)
                    if self._working_memory is not None:
                        self._working_memory.add_message(session_id, tool_msg)
                    if self._audit_logger:
                        self._audit_logger.log_approval_request(user, channel, tc.name, "pending")
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
                async def _execute_one(tc: ToolCall) -> tuple[ToolCall, str, float]:
                    t_start = time.monotonic()
                    try:
                        result = await asyncio.wait_for(
                            self._tools.execute(tc.name, tc.arguments),
                            timeout=self._tool_timeout,
                        )
                        # Check for tool gap
                        if result.not_found and self._tool_gap_detector:
                            try:
                                gap_result = await self._tool_gap_detector.check_and_resolve(
                                    tc.name, tc.arguments, user, channel,
                                )
                                elapsed = (time.monotonic() - t_start) * 1000
                                return tc, f"[success=False] {gap_result.message}", elapsed
                            except Exception as e:
                                logger.error(f"ToolGapDetector error: {e}")
                        elapsed = (time.monotonic() - t_start) * 1000
                        prefix = f"[success={result.success}]"
                        return tc, f"{prefix} {result.output}", elapsed
                    except asyncio.TimeoutError:
                        elapsed = (time.monotonic() - t_start) * 1000
                        return tc, f"[success=False] Tool execution timed out after {self._tool_timeout}s.", elapsed
                    except Exception as e:
                        elapsed = (time.monotonic() - t_start) * 1000
                        logger.exception(f"Tool execution error: {tc.name}")
                        return tc, f"[success=False] Tool execution error: {e}", elapsed

                results = await asyncio.gather(
                    *[_execute_one(tc) for tc in executable_calls]
                )

                for tc, output, elapsed_ms in results:
                    success = "[success=True]" in output
                    logger.info(json.dumps({
                        "event": "tool_call",
                        "tool": tc.name,
                        "success": success,
                        "duration_ms": round(elapsed_ms, 2),
                    }))
                    if self._audit_logger:
                        self._audit_logger.log_tool_call(
                            user, channel, tc.name, tc.arguments,
                            output, success, elapsed_ms,
                        )

                    tool_msg = LLMMessage(
                        role="tool", content=output,
                        tool_call_id=tc.id, name=tc.name,
                    )
                    messages.append(tool_msg)
                    if self._working_memory is not None:
                        self._working_memory.add_message(session_id, tool_msg)

        logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel, "reason": "max_turns"}))
        return "Maximum tool call turns reached. Please try a simpler request."
