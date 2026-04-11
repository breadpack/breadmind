"""FlowEngine: listens for flow events, dispatches steps when ready, completes flows."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol
from uuid import UUID

from breadmind.flow.dag import DAG
from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent

logger = logging.getLogger(__name__)


class StepDispatcher(Protocol):
    async def dispatch(
        self, flow_id: UUID, step_id: str, tool: str | None, args: dict[str, Any]
    ) -> None: ...


class _FlowState:
    def __init__(self) -> None:
        self.dag: DAG | None = None
        self.completed: set[str] = set()
        self.failed: set[str] = set()
        self.queued: set[str] = set()
        self.running: set[str] = set()
        self.finalized: bool = False

    def all_done(self) -> bool:
        if self.dag is None:
            return False
        total = {s.id for s in self.dag.steps}
        return self.completed == total and not self.running and not self.queued


class FlowEngine:
    def __init__(self, bus: FlowEventBus, dispatcher: StepDispatcher) -> None:
        self._bus = bus
        self._dispatcher = dispatcher
        self._states: dict[UUID, _FlowState] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._ready = asyncio.Event()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._ready.clear()
        self._task = asyncio.create_task(self._run())
        # Wait for the subscribe loop to register before returning so that
        # callers can publish events immediately without racing the engine.
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("flow engine subscribe did not ready within 1s")

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
        gen = self._bus.subscribe("flow-engine")
        try:
            # Prime the async generator: calling __anext__ executes the body
            # up to the first await, which registers the subscription
            # synchronously with the bus. We wrap it in a task so we can
            # signal readiness as soon as the registration has happened.
            first = asyncio.ensure_future(gen.__anext__())
            # Yield control so the generator body begins executing and
            # registers the subscription before we set the ready flag.
            await asyncio.sleep(0)
            self._ready.set()
            event = await first
            while True:
                if not self._running:
                    return
                try:
                    await self._handle(event)
                except Exception as exc:
                    logger.error("engine handle error: %s", exc, exc_info=True)
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

    def _state(self, flow_id: UUID) -> _FlowState:
        st = self._states.get(flow_id)
        if st is None:
            st = _FlowState()
            self._states[flow_id] = st
        return st

    async def _handle(self, event: FlowEvent) -> None:
        st = self._state(event.flow_id)
        etype = event.event_type

        if etype == EventType.DAG_PROPOSED:
            st.dag = DAG.from_payload(event.payload.get("steps", []))
            await self._schedule_next(event.flow_id, st)
        elif etype == EventType.STEP_STARTED:
            sid = event.payload["step_id"]
            st.queued.discard(sid)
            st.running.add(sid)
        elif etype == EventType.STEP_COMPLETED:
            sid = event.payload["step_id"]
            st.running.discard(sid)
            st.queued.discard(sid)
            st.completed.add(sid)
            if st.all_done() and not st.finalized:
                st.finalized = True
                await self._bus.publish(
                    FlowEvent(
                        flow_id=event.flow_id,
                        seq=0,
                        event_type=EventType.FLOW_COMPLETED,
                        payload={
                            "summary": {
                                "total_steps": len(st.dag.steps) if st.dag else 0
                            }
                        },
                        actor=FlowActor.ENGINE,
                    )
                )
            else:
                await self._schedule_next(event.flow_id, st)
        elif etype == EventType.STEP_FAILED:
            sid = event.payload["step_id"]
            st.running.discard(sid)
            st.queued.discard(sid)
            st.failed.add(sid)
            # Do not finalize here; wait for the recovery controller to
            # either retry the step or escalate via ESCALATION_RAISED.
        elif etype == EventType.ESCALATION_RAISED:
            if not st.finalized:
                st.finalized = True
                await self._bus.publish(
                    FlowEvent(
                        flow_id=event.flow_id,
                        seq=0,
                        event_type=EventType.FLOW_FAILED,
                        payload={
                            "reason": event.payload.get("reason", "escalated"),
                            "from_step": event.payload.get("step_id"),
                        },
                        actor=FlowActor.ENGINE,
                    )
                )
        elif etype == EventType.DAG_MUTATED:
            if st.dag is None or st.finalized:
                return
            from breadmind.flow.dag import DAGMutation, DAGValidationError
            mutation = DAGMutation(
                added=list(event.payload.get("added", [])),
                removed=list(event.payload.get("removed", [])),
                modified=list(event.payload.get("modified", [])),
            )
            try:
                new_dag = st.dag.apply_mutation(mutation)
            except DAGValidationError as exc:
                await self._bus.publish(
                    FlowEvent(
                        flow_id=event.flow_id,
                        seq=0,
                        event_type=EventType.DAG_MUTATION_REJECTED,
                        payload={"reason": str(exc), "mutation": event.payload},
                        actor=FlowActor.ENGINE,
                    )
                )
                return

            removed_set = set(mutation.removed)
            st.completed -= removed_set
            st.failed -= removed_set
            st.queued -= removed_set
            st.running -= removed_set

            st.dag = new_dag
            await self._schedule_next(event.flow_id, st)
        elif etype == EventType.STEP_QUEUED:
            sid = event.payload["step_id"]
            st.queued.add(sid)
            # Clear any prior failure marker if recovery re-queues the step.
            st.failed.discard(sid)

    async def _schedule_next(self, flow_id: UUID, st: _FlowState) -> None:
        if st.dag is None:
            return
        ready = st.dag.ready_steps(st.completed)
        for sid in ready:
            if sid in st.queued or sid in st.running:
                continue
            step = next((s for s in st.dag.steps if s.id == sid), None)
            if step is None:
                continue
            st.queued.add(sid)
            await self._bus.publish(
                FlowEvent(
                    flow_id=flow_id,
                    seq=0,
                    event_type=EventType.STEP_QUEUED,
                    payload={"step_id": sid},
                    actor=FlowActor.ENGINE,
                )
            )
            try:
                await self._dispatcher.dispatch(flow_id, sid, step.tool, step.args)
            except Exception as exc:
                logger.error("dispatch failed for %s/%s: %s", flow_id, sid, exc)
                await self._bus.publish(
                    FlowEvent(
                        flow_id=flow_id,
                        seq=0,
                        event_type=EventType.STEP_FAILED,
                        payload={"step_id": sid, "error": str(exc), "attempt": 1},
                        actor=FlowActor.ENGINE,
                    )
                )
