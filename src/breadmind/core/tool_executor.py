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
from breadmind.tools.registry import ToolRegistry
from breadmind.core.safety import SafetyGuard, SafetyResult

if TYPE_CHECKING:
    from breadmind.core.audit import AuditLogger
    from breadmind.core.sandbox_executor import SandboxExecutor
    from breadmind.core.tool_gap import ToolGapDetector
    from breadmind.core.tool_hooks import ToolHookRunner
    from breadmind.tools.schema_validator import SchemaValidator

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
    on_new_tool_detected: object | None = None  # async callback(cmd, output)
    _injected_provider: object | None = None  # LLMProvider for subagent tools


class ToolExecutor:
    """Handles tool call filtering, safety checks, cooldown, and parallel execution."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        tool_timeout: int = 30,
        sandbox_executor: SandboxExecutor | None = None,
        hook_runner: ToolHookRunner | None = None,
        schema_validator: SchemaValidator | None = None,
    ):
        self._tools = tool_registry
        self._guard = safety_guard
        self._tool_timeout = tool_timeout
        self._sandbox = sandbox_executor
        self._hook_runner = hook_runner
        self._validator = schema_validator

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
        # Push approval request to UI via EventBus
        from breadmind.core.events import get_event_bus, Event, EventType
        asyncio.ensure_future(get_event_bus().publish(Event(
            type=EventType.PROGRESS,
            data={
                "status": "approval_request",
                "detail": json.dumps({
                    "approval_id": approval_id,
                    "tool": tc.name,
                    "args": tc.arguments,
                }),
            },
            source="tool_executor",
        )))
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
        from breadmind.core.events import get_event_bus, Event, EventType
        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.PROGRESS,
            data={"status": "tool_call", "detail": tool_names},
            source="tool_executor",
        ))

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
                from breadmind.storage.credential_vault import CredentialVault
                clean_output = CredentialVault.sanitize_text(output)
                stored_msg = LLMMessage(
                    role="tool", content=clean_output,
                    tool_call_id=tc.id, name=tc.name,
                )
                ctx.working_memory.add_message(ctx.session_id, stored_msg)

    async def _execute_one(
        self, tc: ToolCall, ctx: ToolExecutionContext,
    ) -> tuple[ToolCall, str, float]:
        """Execute a single tool call with timeout and error handling."""
        t_start = time.monotonic()
        try:
            # Use sandbox for shell commands if available
            if self._sandbox and tc.name == "shell_exec":
                command = tc.arguments.get("command", "")
                workdir = tc.arguments.get("workdir")
                sandbox_result = await self._sandbox.execute(command, workdir)
                elapsed = (time.monotonic() - t_start) * 1000
                prefix = f"[success={sandbox_result.success}]"
                return tc, f"{prefix} {sandbox_result.output}", elapsed

            # Pre-hooks: may block or modify arguments
            if self._hook_runner:
                from breadmind.core.tool_hooks import ToolHookResult
                hook_result = await self._hook_runner.run_pre_hooks(tc.name, tc.arguments)
                if hook_result.action == "block":
                    elapsed = (time.monotonic() - t_start) * 1000
                    return tc, f"[success=False] Blocked by hook: {hook_result.block_reason}", elapsed
                if hook_result.action == "modify" and hook_result.modified_input:
                    tc_arguments = hook_result.modified_input  # use modified args
                else:
                    tc_arguments = tc.arguments
            else:
                tc_arguments = tc.arguments

            # Schema validation
            if self._validator and tc.name in [d.name for d in self._tools.get_all_definitions()]:
                defn = next((d for d in self._tools.get_all_definitions() if d.name == tc.name), None)
                if defn and defn.parameters:
                    from breadmind.tools.schema_validator import SchemaValidator
                    vr = self._validator.validate(tc_arguments, defn.parameters)
                    if not vr.valid:
                        errors = "; ".join(f"{e.field}: {e.message}" for e in vr.errors)
                        elapsed = (time.monotonic() - t_start) * 1000
                        return tc, f"[success=False] Validation failed: {errors}", elapsed

            # Determine timeout
            timeout = self._tool_timeout
            no_timeout = False

            if tc.name == "code_delegate":
                is_long = tc_arguments.get("long_running", False)
                if isinstance(is_long, str):
                    is_long = is_long.lower() in ("true", "1", "yes")
                if is_long:
                    no_timeout = True
                else:
                    timeout = max(self._tool_timeout, 600)

            # Execute: no timeout for long-running, otherwise use asyncio.wait_for
            if no_timeout:
                logger.info("Executing %s with NO timeout (long_running)", tc.name)
                result = await self._tools.execute(tc.name, tc_arguments)
            else:
                logger.info("Executing %s with timeout=%ds", tc.name, timeout)
                result = await asyncio.wait_for(
                    self._tools.execute(tc.name, tc_arguments),
                    timeout=timeout,
                )
            # Check for tool gap
            if result.not_found and ctx.tool_gap_detector:
                try:
                    gap_result = await ctx.tool_gap_detector.check_and_resolve(
                        tc.name, tc_arguments, ctx.user, ctx.channel,
                    )
                    elapsed = (time.monotonic() - t_start) * 1000
                    return tc, f"[success=False] {gap_result.message}", elapsed
                except Exception as e:
                    logger.error(f"ToolGapDetector error: {e}")
            elapsed = (time.monotonic() - t_start) * 1000
            output = f"[success={result.success}] {result.output}"
            success = result.success

            # Post-hooks: may append context
            if self._hook_runner:
                post_result = await self._hook_runner.run_post_hooks(tc.name, tc.arguments, output, success)
                if post_result.additional_context:
                    output += f"\n[Hook context] {post_result.additional_context}"

            return tc, output, elapsed
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - t_start) * 1000
            return tc, f"[success=False] Tool execution timed out after {timeout}s.", elapsed
        except Exception as e:
            elapsed = (time.monotonic() - t_start) * 1000
            logger.exception(f"Tool execution error: {tc.name}")
            return tc, f"[success=False] Tool execution error: {e}", elapsed
