"""Tool execution, safety verification, cooldown management, and parallel execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, ToolCall
from breadmind.tools.registry import ToolRegistry
from breadmind.core.safety import SafetyGuard, SafetyResult
from breadmind.tools.browser_screenshot import (
    is_browser_tool,
    process_tool_result as process_browser_result,
)

if TYPE_CHECKING:
    from breadmind.core.audit import AuditLogger
    from breadmind.core.sandbox_executor import SandboxExecutor
    from breadmind.core.tool_gap import ToolGapDetector
    from breadmind.core.tool_hooks import ToolHookRunner
    from breadmind.memory.episodic_recorder import EpisodicRecorder
    from breadmind.memory.episodic_store import EpisodicStore
    from breadmind.memory.signals import SignalDetector
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
        *,
        episodic_store: EpisodicStore | None = None,
        episodic_recorder: EpisodicRecorder | None = None,
        signal_detector: SignalDetector | None = None,
    ):
        self._tools = tool_registry
        self._guard = safety_guard
        self._tool_timeout = tool_timeout
        self._sandbox = sandbox_executor
        self._hook_runner = hook_runner
        self._validator = schema_validator

        # Episodic memory wiring (Phase 1, T9). All optional — when both store
        # and recorder are absent, the no-memory hot path is zero-cost.
        self._episodic_store = episodic_store
        self._episodic_recorder = episodic_recorder
        if signal_detector is None and (episodic_store is not None or episodic_recorder is not None):
            from breadmind.memory.signals import SignalDetector as _SD
            signal_detector = _SD()
        self._signal_detector = signal_detector

        # Last pre-call recall results, exposed for ContextBuilder to render
        # into the next LLM prompt. T11/T12 wires this into the actual prompt
        # template; for now ToolExecutor only stores the raw notes list so the
        # caller (CoreAgent / context layer) can pick it up.
        self._last_recall_notes: list = []

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

    async def execute(
        self,
        *,
        tool_name: str,
        args: dict | None,
        user_id: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> str:
        """Lightweight per-tool entry point with episodic recall + signal hook.

        Used by callers that want pre-call recall of prior runs of the same
        tool and a post-call SignalEvent emitted to ``EpisodicRecorder``.

        Returns the raw tool output string (with the same ``[success=...]``
        prefix produced elsewhere in this module). Recall failures are logged
        and swallowed — they MUST NEVER block tool execution. Recorder calls
        are fire-and-forget.

        Note: ``self._last_recall_notes`` is populated as a list of
        ``EpisodicNote`` objects. T11 will introduce the rendering partial
        (``render_previous_runs_for_tool``) that feeds these into the prompt;
        until then, callers should treat this as opaque state.
        """
        args = args or {}

        # ── Pre-call recall ─────────────────────────────────────────
        await self._do_recall(tool_name=tool_name, args=args, user_id=user_id)

        # ── Tool execution ──────────────────────────────────────────
        t_start = time.monotonic()
        ok = True
        try:
            result = await asyncio.wait_for(
                self._tools.execute(tool_name, args),
                timeout=self._tool_timeout,
            )
            ok = bool(getattr(result, "success", True))
            output_body = getattr(result, "output", str(result))
            output = f"[success={ok}] {output_body}"
        except asyncio.TimeoutError:
            ok = False
            output = f"[success=False] Tool execution timed out after {self._tool_timeout}s."
        except Exception as e:
            ok = False
            output = f"[success=False] Tool execution error: {e}"
        elapsed = (time.monotonic() - t_start) * 1000
        logger.debug(
            "ToolExecutor.execute %s ok=%s elapsed_ms=%.2f", tool_name, ok, elapsed,
        )

        # ── Post-call signal + fire-and-forget record ───────────────
        self._emit_tool_signal(
            tool_name=tool_name,
            tool_args=args,
            ok=ok,
            result_text=output,
            user_id=user_id,
            session_id=session_id,
        )

        return output

    async def _do_recall(
        self,
        *,
        tool_name: str,
        args: dict,
        user_id: str | None,
    ) -> None:
        """Pre-call episodic recall — populates ``self._last_recall_notes``.

        Shared between :meth:`execute` (the standalone per-tool entrypoint)
        and :meth:`_execute_one` (the production agent path used inside
        ``process_tool_calls``). Failures are warned and swallowed — recall
        MUST NEVER block tool execution.
        """
        if self._episodic_store is None:
            self._last_recall_notes = []
            return
        # T13: trigger counter fires once per attempt; the hit-count histogram
        # observation happens after search returns (or with 0 on failure).
        from breadmind.memory.metrics import (
            memory_recall_hit_count,
            memory_recall_total,
        )
        try:
            memory_recall_total.labels(trigger="tool").inc()
        except Exception:  # pragma: no cover - defensive
            logger.debug("memory_recall_total inc failed", exc_info=True)
        try:
            from breadmind.memory.episodic_store import EpisodicFilter
            from breadmind.memory.event_types import (
                SignalKind,
                keyword_extract,
                stable_hash,
            )

            limit = int(os.getenv("BREADMIND_EPISODIC_RECALL_TOOL_K", "3"))
            kw = keyword_extract(args) if args else []
            flt = EpisodicFilter(
                kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
                tool_name=tool_name,
                tool_args_digest=stable_hash(args),
                keywords=kw or None,
            )
            notes = await self._episodic_store.search(
                user_id=user_id,
                query=None,
                filters=flt,
                limit=limit,
            )
            self._last_recall_notes = list(notes or [])
            try:
                memory_recall_hit_count.observe(float(len(self._last_recall_notes)))
            except Exception:  # pragma: no cover - defensive
                logger.debug("recall_hit_count observe failed", exc_info=True)
        except Exception:
            logger.warning("episodic recall failed", exc_info=True)
            self._last_recall_notes = []
            try:
                memory_recall_hit_count.observe(0.0)
            except Exception:  # pragma: no cover - defensive
                logger.debug("recall_hit_count observe failed", exc_info=True)

    def _emit_tool_signal(
        self,
        *,
        tool_name: str,
        tool_args: dict,
        ok: bool,
        result_text: str,
        user_id: str | None,
        session_id: uuid.UUID | None,
    ) -> None:
        """Post-call signal + fire-and-forget record.

        Shared between :meth:`execute` and :meth:`_execute_one`. No-op when
        either ``signal_detector`` or ``episodic_recorder`` is missing.
        Recorder errors are absorbed in ``_safe_record``.

        ``session_id`` is intentionally typed as ``uuid.UUID | None``: the
        production agent path only has a string session id, so callers must
        pass ``None`` when their session id is not a UUID (mirroring the
        approach taken by ``CoreAgent._emit_user_signal``).
        """
        if self._signal_detector is None or self._episodic_recorder is None:
            return
        try:
            from breadmind.memory.signals import TurnSnapshot

            # Truncate long tool outputs before passing into the signal —
            # the recorder will normalize them downstream, but huge bodies
            # are pointless to drag through the queue.
            truncated = (result_text or "")[:4000]

            snap = TurnSnapshot(
                user_id=user_id or "",
                session_id=session_id,
                user_message="",
                last_tool_name=tool_name,
                prior_turn_summary=None,
            )
            evt = self._signal_detector.on_tool_finished(
                snap,
                tool_name=tool_name,
                tool_args=tool_args,
                ok=ok,
                result_text=truncated,
            )
            recorder = self._episodic_recorder

            async def _safe_record():
                try:
                    await recorder.record(evt)
                except Exception:
                    logger.debug("episodic recorder failed", exc_info=True)

            try:
                asyncio.create_task(_safe_record())
            except RuntimeError:
                # No running loop (sync context) — drop silently.
                logger.debug("could not schedule recorder task", exc_info=True)
        except Exception:
            logger.warning(
                "ToolExecutor _emit_tool_signal swallowed", exc_info=True,
            )

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
            # Extract screenshots/PDFs from browser tool results into Attachments
            if is_browser_tool(tc.name):
                cleaned, attachments = process_browser_result(tool_msg.content or "")
                if attachments:
                    tool_msg.content = cleaned
                    tool_msg.attachments = attachments
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
        """Execute a single tool call with timeout and error handling.

        After the call (success or failure) emits the episodic TOOL signal
        through :meth:`_emit_tool_signal`. Pre-call episodic recall runs once
        we know the effective args (i.e. after pre-hooks may rewrite them).
        """
        t_start = time.monotonic()
        ok = False
        output = ""
        # Track effective args used so the post-call signal reflects what
        # actually ran (after potential hook rewrite).
        effective_args = dict(tc.arguments) if tc.arguments else {}
        # Default timeout in case we hit asyncio.TimeoutError before the
        # branch that assigns ``timeout`` runs.
        timeout = self._tool_timeout
        try:
            # Use sandbox for shell commands if available
            if self._sandbox and tc.name == "shell_exec":
                command = tc.arguments.get("command", "")
                workdir = tc.arguments.get("workdir")
                # Pre-call recall — best effort; uses the raw args.
                await self._do_recall(
                    tool_name=tc.name,
                    args=effective_args,
                    user_id=ctx.user,
                )
                sandbox_result = await self._sandbox.execute(command, workdir)
                elapsed = (time.monotonic() - t_start) * 1000
                ok = bool(getattr(sandbox_result, "success", True))
                prefix = f"[success={ok}]"
                output = f"{prefix} {sandbox_result.output}"
                return tc, output, elapsed

            # Pre-hooks: may block or modify arguments
            if self._hook_runner:
                hook_result = await self._hook_runner.run_pre_hooks(tc.name, tc.arguments)
                if hook_result.action == "block":
                    elapsed = (time.monotonic() - t_start) * 1000
                    ok = False
                    output = f"[success=False] Blocked by hook: {hook_result.block_reason}"
                    return tc, output, elapsed
                if hook_result.action == "modify" and hook_result.modified_input:
                    tc_arguments = hook_result.modified_input  # use modified args
                else:
                    tc_arguments = tc.arguments
            else:
                tc_arguments = tc.arguments
            effective_args = dict(tc_arguments) if tc_arguments else {}

            # Schema validation
            if self._validator and tc.name in [d.name for d in self._tools.get_all_definitions()]:
                defn = next((d for d in self._tools.get_all_definitions() if d.name == tc.name), None)
                if defn and defn.parameters:
                    vr = self._validator.validate(tc_arguments, defn.parameters)
                    if not vr.valid:
                        errors = "; ".join(f"{e.field}: {e.message}" for e in vr.errors)
                        elapsed = (time.monotonic() - t_start) * 1000
                        ok = False
                        output = f"[success=False] Validation failed: {errors}"
                        return tc, output, elapsed

            # Pre-call episodic recall (now that we know the effective args).
            await self._do_recall(
                tool_name=tc.name,
                args=effective_args,
                user_id=ctx.user,
            )

            # Determine timeout
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
                    ok = False
                    output = f"[success=False] {gap_result.message}"
                    return tc, output, elapsed
                except Exception as e:
                    logger.error(f"ToolGapDetector error: {e}")
            elapsed = (time.monotonic() - t_start) * 1000
            ok = bool(result.success)
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
            ok = False
            output = f"[success=False] Tool execution timed out after {timeout}s."
            return tc, output, elapsed
        except Exception as e:
            elapsed = (time.monotonic() - t_start) * 1000
            ok = False
            output = f"[success=False] Tool execution error: {e}"
            logger.exception(f"Tool execution error: {tc.name}")
            return tc, output, elapsed
        finally:
            # Always emit the episodic signal — every return path above sets
            # ``ok`` and ``output`` before reaching here. Helper is a no-op
            # when memory deps are not wired.
            self._emit_tool_signal(
                tool_name=tc.name,
                tool_args=effective_args,
                ok=ok,
                result_text=output,
                user_id=ctx.user,
                session_id=None,  # ctx.session_id is a string, not UUID
            )
