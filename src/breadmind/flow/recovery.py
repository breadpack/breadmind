"""RecoveryController: Layer 1 rule-based step recovery.

Listens to the flow event bus and reacts to ``STEP_FAILED`` events by
either:

1. Retrying the step with exponential backoff when the error is
   classified as transient and the retry budget has not been exhausted.
2. Raising an ``ESCALATION_RAISED`` event which the :class:`FlowEngine`
   finalizes into ``FLOW_FAILED``.

This is Layer 1 of the Durable Task Flow recovery hierarchy: rule-based
retries with no LLM involvement.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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


class RecoveryController:
    """Rule-based layer 1 recovery for durable task flows."""

    def __init__(
        self,
        bus: FlowEventBus,
        dispatcher: StepDispatcher,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._bus = bus
        self._dispatcher = dispatcher
        self._policy = policy or RetryPolicy()
        self._task: asyncio.Task | None = None
        self._running = False
        self._ready = asyncio.Event()
        # Cache of step definitions keyed by (flow_id, step_id) so we can
        # re-dispatch without replaying the event history.
        self._step_cache: dict[tuple[UUID, str], dict] = {}

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
            await self._escalate(flow_id, sid, "non-transient error", error)
            return

        if attempt >= self._policy.max_attempts:
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
