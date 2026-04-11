"""RecoveryController: Layer 1 + Layer 2 step recovery.

Listens to the flow event bus and reacts to ``STEP_FAILED`` events by:

1. **Layer 1** (rule-based): Retrying the step with exponential backoff
   when the error is classified as transient and the retry budget has
   not been exhausted.
2. **Layer 2** (LLM-based, optional): When rule-based retries are
   exhausted (or error is non-transient), consult an LLM to propose an
   adaptive recovery strategy (modify args, swap tool, skip, or
   escalate).
3. **Escalate**: Raising an ``ESCALATION_RAISED`` event which the
   :class:`FlowEngine` finalizes into ``FLOW_FAILED``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from breadmind.flow.engine import StepDispatcher
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent

logger = logging.getLogger(__name__)


# Substrings that, when present in a step error message, mark the failure
# as transient and therefore a candidate for rule-based retry.
TRANSIENT_MARKERS = (
    "ConnectionError",
    "TimeoutError",
    "timeout",
    "Temporary",
    "TemporaryFailure",
    "EOF",
    "Connection reset",
    "429",
    " 500",
    " 502",
    " 503",
    " 504",
)


def is_transient_error(message: str) -> bool:
    """Return True if *message* looks like a transient / retriable error."""
    if not message:
        return False
    msg_lower = message.lower()
    for marker in TRANSIENT_MARKERS:
        if marker.lower() in msg_lower:
            return True
    return False


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 1.0
    backoff_factor: float = 2.0
    max_delay: float = 60.0
    max_llm_attempts: int = 3


RECOVERY_SYSTEM_PROMPT = (
    "You are a recovery planner for a task execution system. A step has "
    "failed. Your job is to propose a recovery strategy.\n\n"
    "Respond with ONLY a JSON object (no markdown, no prose):\n"
    "{\n"
    '  "strategy": "retry_with_modified_args" | "replace_step_with_alternative" | "skip_and_continue" | "escalate",\n'
    '  "reasoning": "brief explanation",\n'
    '  "args": { ... },          // required for retry_with_modified_args and replace_step_with_alternative\n'
    '  "tool": "tool_name"       // required only for replace_step_with_alternative\n'
    "}\n\n"
    "Choose based on:\n"
    "- retry_with_modified_args: the step could succeed with different "
    "arguments (e.g., fix a typo in a command, use a different URL)\n"
    "- replace_step_with_alternative: the tool itself is wrong; a "
    "different tool would work better\n"
    "- skip_and_continue: the step is not critical and the flow can "
    "proceed without it\n"
    "- escalate: the failure requires human judgment; none of the above apply"
)

VALID_STRATEGIES = {
    "retry_with_modified_args",
    "replace_step_with_alternative",
    "skip_and_continue",
    "escalate",
}


class RecoveryController:
    """Layer 1 + Layer 2 recovery for durable task flows."""

    def __init__(
        self,
        bus: FlowEventBus,
        dispatcher: StepDispatcher,
        policy: RetryPolicy | None = None,
        llm: Any | None = None,
    ) -> None:
        self._bus = bus
        self._dispatcher = dispatcher
        self._policy = policy or RetryPolicy()
        self._llm = llm
        self._task: asyncio.Task | None = None
        self._running = False
        self._ready = asyncio.Event()
        # Cache of step definitions keyed by (flow_id, step_id) so we can
        # re-dispatch without replaying the event history.
        self._step_cache: dict[tuple[UUID, str], dict] = {}
        # Count of Layer 2 LLM attempts per step.
        self._llm_attempts: dict[tuple[UUID, str], int] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._ready.clear()
        self._task = asyncio.create_task(self._run())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("recovery controller subscribe did not ready within 1s")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        gen = self._bus.subscribe("recovery-controller")
        try:
            # Prime the async generator so the subscription is registered
            # synchronously before we signal readiness (same pattern as
            # FlowEngine._run).
            first = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0)
            self._ready.set()
            event = await first
            while True:
                if not self._running:
                    return
                try:
                    await self._handle(event)
                except Exception as exc:
                    logger.error("recovery handle error: %s", exc, exc_info=True)
                event = await gen.__anext__()
        except StopAsyncIteration:
            return
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await gen.aclose()
            except Exception:
                pass

    async def _handle(self, event: FlowEvent) -> None:
        etype = event.event_type
        if etype == EventType.DAG_PROPOSED:
            for step in event.payload.get("steps", []) or []:
                sid = step.get("id")
                if sid is not None:
                    self._step_cache[(event.flow_id, sid)] = step
        elif etype == EventType.STEP_FAILED:
            await self._try_recover(event)

    async def _try_recover(self, event: FlowEvent) -> None:
        flow_id = event.flow_id
        sid = event.payload["step_id"]
        error = event.payload.get("error", "") or ""
        try:
            attempt = int(event.payload.get("attempt", 1))
        except (TypeError, ValueError):
            attempt = 1

        if not is_transient_error(error):
            # Layer 2: try LLM-based recovery before escalating.
            if await self._maybe_llm_recover(
                flow_id, sid, error, attempt, "non-transient error"
            ):
                return
            await self._escalate(flow_id, sid, "non-transient error", error)
            return

        if attempt >= self._policy.max_attempts:
            # Layer 2: try LLM-based recovery before escalating.
            if await self._maybe_llm_recover(
                flow_id, sid, error, attempt, "max attempts exceeded"
            ):
                return
            await self._escalate(flow_id, sid, "max attempts exceeded", error)
            return

        delay = min(
            self._policy.initial_delay
            * (self._policy.backoff_factor ** (attempt - 1)),
            self._policy.max_delay,
        )
        if delay > 0:
            await asyncio.sleep(delay)

        next_attempt = attempt + 1
        await self._bus.publish(
            FlowEvent(
                flow_id=flow_id,
                seq=0,
                event_type=EventType.RECOVERY_ATTEMPTED,
                payload={
                    "step_id": sid,
                    "strategy": "rule_retry",
                    "attempt": next_attempt,
                    "delay": delay,
                },
                actor=FlowActor.RECOVERY,
            )
        )

        step = self._step_cache.get((flow_id, sid))
        if step is None:
            logger.warning(
                "recovery: step %s/%s missing from cache, cannot retry",
                flow_id,
                sid,
            )
            await self._escalate(
                flow_id, sid, "step definition unavailable", error
            )
            return

        # Re-queue the step via STEP_QUEUED so the engine clears its
        # prior failure marker, then dispatch directly to the worker.
        await self._bus.publish(
            FlowEvent(
                flow_id=flow_id,
                seq=0,
                event_type=EventType.STEP_QUEUED,
                payload={"step_id": sid, "attempt": next_attempt},
                actor=FlowActor.RECOVERY,
            )
        )
        try:
            await self._dispatcher.dispatch(
                flow_id, sid, step.get("tool"), step.get("args", {}) or {}
            )
        except Exception as exc:
            logger.error("retry dispatch failed for %s/%s: %s", flow_id, sid, exc)
            await self._escalate(flow_id, sid, "retry dispatch failed", str(exc))

    async def _maybe_llm_recover(
        self,
        flow_id: UUID,
        step_id: str,
        error: str,
        attempt: int,
        rule_reason: str,
    ) -> bool:
        """Attempt Layer 2 LLM recovery.

        Returns True if a recovery action was taken (or LLM explicitly
        chose to escalate) so the caller must not fall through to its
        own escalation path. Returns False if Layer 2 is unavailable
        (no llm configured, budget exhausted, or step not cached).
        """
        if self._llm is None:
            return False
        key = (flow_id, step_id)
        used = self._llm_attempts.get(key, 0)
        if used >= self._policy.max_llm_attempts:
            return False
        step = self._step_cache.get(key)
        if step is None:
            return False
        self._llm_attempts[key] = used + 1
        try:
            await self._llm_recover(
                flow_id, step_id, step, error, attempt, rule_reason
            )
            return True
        except Exception as exc:
            logger.error(
                "llm recovery failed for %s/%s: %s",
                flow_id,
                step_id,
                exc,
                exc_info=True,
            )
            await self._escalate(
                flow_id, step_id, "llm recovery error", str(exc)
            )
            return True

    async def _llm_recover(
        self,
        flow_id: UUID,
        step_id: str,
        step: dict,
        error: str,
        attempt: int,
        rule_reason: str,
    ) -> None:
        """Build prompt, call LLM, parse response, apply strategy."""
        title = step.get("title") or step_id
        tool = step.get("tool")
        args = step.get("args", {}) or {}

        user_text = (
            "Step that failed:\n"
            f"  id: {step_id}\n"
            f"  title: {title}\n"
            f"  tool: {tool}\n"
            f"  args: {json.dumps(args)}\n\n"
            "Error:\n"
            f"{error}\n\n"
            f"Attempts so far: {attempt}\n\n"
            "Propose a recovery strategy."
        )
        messages = [
            {"role": "system", "content": RECOVERY_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        resp = await self._llm.chat(messages)
        content = getattr(resp, "content", None)
        if not content:
            raise ValueError("llm returned empty content")

        try:
            plan = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"llm response not valid JSON: {exc}") from exc

        strategy = plan.get("strategy")
        reasoning = plan.get("reasoning", "")
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"unknown recovery strategy: {strategy!r}")

        key = (flow_id, step_id)

        if strategy == "retry_with_modified_args":
            new_args = plan.get("args")
            if not isinstance(new_args, dict):
                raise ValueError(
                    "retry_with_modified_args missing 'args' object"
                )
            self._step_cache[key]["args"] = new_args
            await self._publish_recovery_attempt(
                flow_id,
                step_id,
                "llm_retry_with_modified_args",
                {"reasoning": reasoning, "args": new_args},
            )
            await self._bus.publish(
                FlowEvent(
                    flow_id=flow_id,
                    seq=0,
                    event_type=EventType.STEP_QUEUED,
                    payload={"step_id": step_id, "attempt": attempt + 1},
                    actor=FlowActor.RECOVERY,
                )
            )
            await self._dispatcher.dispatch(
                flow_id, step_id, self._step_cache[key].get("tool"), new_args
            )
            return

        if strategy == "replace_step_with_alternative":
            new_tool = plan.get("tool")
            new_args = plan.get("args")
            if not new_tool or not isinstance(new_args, dict):
                raise ValueError(
                    "replace_step_with_alternative missing 'tool' or 'args'"
                )
            self._step_cache[key]["tool"] = new_tool
            self._step_cache[key]["args"] = new_args
            await self._publish_recovery_attempt(
                flow_id,
                step_id,
                "llm_replace_step_with_alternative",
                {
                    "reasoning": reasoning,
                    "tool": new_tool,
                    "args": new_args,
                },
            )
            await self._bus.publish(
                FlowEvent(
                    flow_id=flow_id,
                    seq=0,
                    event_type=EventType.STEP_QUEUED,
                    payload={"step_id": step_id, "attempt": attempt + 1},
                    actor=FlowActor.RECOVERY,
                )
            )
            await self._dispatcher.dispatch(
                flow_id, step_id, new_tool, new_args
            )
            return

        if strategy == "skip_and_continue":
            await self._publish_recovery_attempt(
                flow_id,
                step_id,
                "llm_skip_and_continue",
                {"reasoning": reasoning},
            )
            await self._bus.publish(
                FlowEvent(
                    flow_id=flow_id,
                    seq=0,
                    event_type=EventType.STEP_COMPLETED,
                    payload={
                        "step_id": step_id,
                        "result": {
                            "skipped": True,
                            "reason": reasoning or "llm skip_and_continue",
                        },
                    },
                    actor=FlowActor.RECOVERY,
                )
            )
            return

        # strategy == "escalate"
        await self._publish_recovery_attempt(
            flow_id,
            step_id,
            "llm_escalate",
            {"reasoning": reasoning},
        )
        await self._escalate(
            flow_id,
            step_id,
            f"llm escalate: {reasoning}" if reasoning else "llm escalate",
            error,
        )

    async def _publish_recovery_attempt(
        self,
        flow_id: UUID,
        step_id: str,
        strategy: str,
        context: dict,
    ) -> None:
        await self._bus.publish(
            FlowEvent(
                flow_id=flow_id,
                seq=0,
                event_type=EventType.RECOVERY_ATTEMPTED,
                payload={
                    "step_id": step_id,
                    "strategy": strategy,
                    "context": context,
                },
                actor=FlowActor.RECOVERY,
            )
        )

    async def _escalate(
        self, flow_id: UUID, step_id: str, reason: str, error: str
    ) -> None:
        await self._bus.publish(
            FlowEvent(
                flow_id=flow_id,
                seq=0,
                event_type=EventType.ESCALATION_RAISED,
                payload={
                    "step_id": step_id,
                    "reason": reason,
                    "error": error,
                    "context": {"recovery_layer": 1},
                },
                actor=FlowActor.RECOVERY,
            )
        )
