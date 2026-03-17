"""Tool execution, safety verification, cooldown management, and parallel execution."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, ToolCall
from breadmind.tools.registry import ToolRegistry, ToolResult
from breadmind.core.safety import SafetyGuard, SafetyResult

if TYPE_CHECKING:
    from breadmind.core.audit import AuditLogger
    from breadmind.core.tool_gap import ToolGapDetector

logger = logging.getLogger("breadmind.agent")


@dataclass
class ToolExecutionContext:
    """Context passed to ToolExecutor for a single handle_message turn."""

    user: str
    channel: str
    session_id: str
    working_memory: object | None  # WorkingMemory
    audit_logger: AuditLogger | None
    tool_gap_detector: ToolGapDetector | None
    context_builder: object | None
    pending_approvals: dict[str, dict] = field(default_factory=dict)
    notify_progress: object | None = None  # async callback(status, detail)
    on_new_tool_detected: object | None = None  # async callback(cmd, output)
    _injected_provider: object | None = None  # LLMProvider for delegate_tasks


class ToolExecutor:
    """Handles tool call filtering, safety checks, cooldown, and parallel execution."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        tool_timeout: int = 30,
    ):
        self._tools = tool_registry
        self._guard = safety_guard
        self._tool_timeout = tool_timeout

    @property
    def tool_timeout(self) -> int:
        return self._tool_timeout

    @tool_timeout.setter
    def tool_timeout(self, value: int) -> None:
        self._tool_timeout = value

    async def process_tool_calls(
        self,
        tool_calls: list[ToolCall],
        messages: list[LLMMessage],
        ctx: ToolExecutionContext,
    ) -> None:
        """Process all tool calls from an LLM response: filter, check safety, execute.

        Modifies `messages` in-place by appending tool result messages.
        """
        executable_calls: list[ToolCall] = []

        for tc in tool_calls:
            result_msg = self._check_tool_call(tc, ctx)
            if result_msg is not None:
                # Tool was blocked, needs approval, or is in cooldown
                messages.append(result_msg)
                if ctx.working_memory is not None:
                    ctx.working_memory.add_message(ctx.session_id, result_msg)
            else:
                executable_calls.append(tc)

        # Execute allowed tool calls in parallel
        if executable_calls:
            await self._execute_calls(executable_calls, messages, ctx)

    def _check_tool_call(
        self, tc: ToolCall, ctx: ToolExecutionContext,
    ) -> LLMMessage | None:
        """Check a single tool call for safety, approval, and cooldown.

        Returns a tool message if the call should NOT be executed,
        or None if the call is allowed to proceed.
        """
        safety = self._guard.check(
            tc.name, tc.arguments, user=ctx.user, channel=ctx.channel,
        )

        if ctx.audit_logger:
            ctx.audit_logger.log_safety_check(
                ctx.user, ctx.channel, tc.name, safety.value,
            )

        if safety == SafetyResult.DENY:
            logger.info(json.dumps({
                "event": "safety_deny", "tool": tc.name, "user": ctx.user,
            }))
            return LLMMessage(
                role="tool",
                content=f"[success=False] BLOCKED: {tc.name} is in the blacklist.",
                tool_call_id=tc.id, name=tc.name,
            )

        if safety == SafetyResult.REQUIRE_APPROVAL:
            return self._handle_approval(tc, ctx)

        # Check cooldown (only for automated/monitoring channels)
        if ctx.channel.startswith("system:") or ctx.channel.startswith("monitoring:"):
            cooldown_target = f"{ctx.user}:{ctx.channel}"
            if not self._guard.check_cooldown(cooldown_target, tc.name):
                return LLMMessage(
                    role="tool",
                    content=f"[success=False] COOLDOWN: {tc.name} is in cooldown. Please wait before retrying.",
                    tool_call_id=tc.id, name=tc.name,
                )

        return None  # Allowed to execute

    def _handle_approval(
        self, tc: ToolCall, ctx: ToolExecutionContext,
    ) -> LLMMessage:
        """Create an approval request for a tool call."""
        approval_id = str(uuid.uuid4())
        ctx.pending_approvals[approval_id] = {
            "tool": tc.name, "args": tc.arguments,
            "user": ctx.user, "channel": ctx.channel, "status": "pending",
        }
        if ctx.audit_logger:
            ctx.audit_logger.log_approval_request(
                ctx.user, ctx.channel, tc.name, "pending",
            )
        # Push approval request to UI immediately via progress callback
        if ctx.notify_progress:
            asyncio.ensure_future(ctx.notify_progress(
                "approval_request",
                json.dumps({
                    "approval_id": approval_id,
                    "tool": tc.name,
                    "args": tc.arguments,
                }),
            ))
        return LLMMessage(
            role="tool",
            content=(
                f"[approval_required] Tool '{tc.name}' requires approval. "
                f"Approval ID: {approval_id}. Ask the user to approve."
            ),
            tool_call_id=tc.id, name=tc.name,
        )

    async def _execute_calls(
        self,
        calls: list[ToolCall],
        messages: list[LLMMessage],
        ctx: ToolExecutionContext,
    ) -> None:
        """Execute tool calls in parallel and append results to messages."""
        tool_names = ", ".join(tc.name for tc in calls)
        if ctx.notify_progress:
            await ctx.notify_progress("tool_call", tool_names)

        results = await asyncio.gather(
            *[self._execute_one(tc, ctx) for tc in calls]
        )

        for tc, output, elapsed_ms in results:
            success = "[success=True]" in output
            logger.info(json.dumps({
                "event": "tool_call",
                "tool": tc.name,
                "success": success,
                "duration_ms": round(elapsed_ms, 2),
            }))
            if ctx.audit_logger:
                ctx.audit_logger.log_tool_call(
                    ctx.user, ctx.channel, tc.name, tc.arguments,
                    output, success, elapsed_ms,
                )

            # Detect newly installed tools from shell_exec output
            if tc.name == "shell_exec" and success and ctx.on_new_tool_detected:
                cmd = tc.arguments.get("command", "")
                asyncio.create_task(ctx.on_new_tool_detected(cmd, output))

            tool_msg = LLMMessage(
                role="tool", content=output,
                tool_call_id=tc.id, name=tc.name,
            )
            messages.append(tool_msg)
            if ctx.working_memory is not None:
                ctx.working_memory.add_message(ctx.session_id, tool_msg)

    async def _execute_one(
        self, tc: ToolCall, ctx: ToolExecutionContext,
    ) -> tuple[ToolCall, str, float]:
        """Execute a single tool call with timeout and error handling."""
        t_start = time.monotonic()
        try:
            # Special handling for delegate_tasks: inject provider and registry
            # directly to bypass schema-based type coercion
            if tc.name == "delegate_tasks":
                from breadmind.tools.builtin import delegate_tasks as _delegate_fn
                _delegate_timeout = self._tool_timeout * 3  # Allow more time for parallel subtasks
                raw_result = await asyncio.wait_for(
                    _delegate_fn(
                        tasks=tc.arguments.get("tasks", "[]"),
                        _agent=None,
                        _provider=ctx._injected_provider,
                        _registry=self._tools,
                    ),
                    timeout=_delegate_timeout,
                )
                from breadmind.tools.registry import ToolResult as _TR, _truncate_output
                output_str = _truncate_output(str(raw_result))
                result = _TR(success=True, output=output_str)
            else:
                result = await asyncio.wait_for(
                    self._tools.execute(tc.name, tc.arguments),
                    timeout=self._tool_timeout,
                )
            # Check for tool gap
            if result.not_found and ctx.tool_gap_detector:
                try:
                    gap_result = await ctx.tool_gap_detector.check_and_resolve(
                        tc.name, tc.arguments, ctx.user, ctx.channel,
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
