"""Celery dispatcher for durable task flow step execution.

Provides:

- ``CeleryStepDispatcher``: implements the :class:`StepDispatcher` protocol by
  sending a Celery task carrying the step payload. Used by ``FlowEngine`` to
  offload step execution to a Celery worker.
- ``execute_flow_step``: async entry point that runs inside a Celery worker
  process. It publishes lifecycle events (STEP_STARTED / STEP_COMPLETED /
  STEP_FAILED) via the flow event bus and executes the configured tool via a
  ``ToolRegistry``.

For Phase 1 of the durable flow system the dispatcher is the critical
deliverable. ``execute_flow_step`` is wired up best-effort; it uses the
worker-local singletons established by ``breadmind.tasks.worker`` when
available, and falls back to a no-op result when those singletons are not
initialized (e.g. when invoked outside of a bootstrapped Celery worker).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from breadmind.flow.engine import StepDispatcher
from breadmind.flow.events import EventType, FlowActor, FlowEvent

logger = logging.getLogger(__name__)


class CeleryStepDispatcher(StepDispatcher):
    """StepDispatcher that forwards step execution to a Celery task.

    The dispatcher is intentionally thin: it serializes step metadata into a
    ``send_task`` call and returns. The Celery worker is responsible for
    actually executing the tool and publishing lifecycle events back to the
    flow event bus.
    """

    def __init__(self, celery: Any, task_name: str = "flow.execute_step") -> None:
        self._celery = celery
        self._task_name = task_name

    async def dispatch(
        self,
        flow_id: UUID,
        step_id: str,
        tool: str | None,
        args: dict[str, Any],
    ) -> None:
        payload = {
            "flow_id": str(flow_id),
            "step_id": step_id,
            "tool": tool,
            "args": args or {},
        }

        def _send() -> None:
            self._celery.send_task(
                self._task_name,
                kwargs=payload,
            )

        # ``send_task`` is synchronous (it talks to the broker). Run it in the
        # default executor so we don't block the event loop on I/O.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send)


async def execute_flow_step(
    flow_id: str,
    step_id: str,
    tool: str | None,
    args: dict[str, Any] | None,
) -> dict[str, Any]:
    """Execute a single flow step inside a Celery worker process.

    Publishes STEP_STARTED before running the tool and STEP_COMPLETED or
    STEP_FAILED afterwards. Event publishing errors are logged but do not
    override the tool execution outcome reported to Celery.
    """
    flow_uuid = UUID(flow_id)
    args = args or {}

    bus = await _build_worker_bus()

    started_at = time.monotonic()

    # STEP_STARTED (best effort)
    await _safe_publish(
        bus,
        FlowEvent(
            flow_id=flow_uuid,
            seq=0,
            event_type=EventType.STEP_STARTED,
            payload={"step_id": step_id},
            actor=FlowActor.WORKER,
        ),
    )

    try:
        result = await _run_tool(tool, args)
    except Exception as tool_exc:  # noqa: BLE001
        logger.error(
            "flow step %s/%s tool %r failed: %s",
            flow_id,
            step_id,
            tool,
            tool_exc,
            exc_info=True,
        )
        await _safe_publish(
            bus,
            FlowEvent(
                flow_id=flow_uuid,
                seq=0,
                event_type=EventType.STEP_FAILED,
                payload={
                    "step_id": step_id,
                    "error": f"{type(tool_exc).__name__}: {tool_exc}",
                    "attempt": 1,
                },
                actor=FlowActor.WORKER,
            ),
        )
        return {"ok": False, "error": str(tool_exc)}

    duration_ms = int((time.monotonic() - started_at) * 1000)
    await _safe_publish(
        bus,
        FlowEvent(
            flow_id=flow_uuid,
            seq=0,
            event_type=EventType.STEP_COMPLETED,
            payload={
                "step_id": step_id,
                "result": result,
                "duration_ms": duration_ms,
            },
            actor=FlowActor.WORKER,
        ),
    )
    return {"ok": True, "result": result, "duration_ms": duration_ms}


# ── Internals ────────────────────────────────────────────────────────


async def _build_worker_bus() -> Any:
    """Construct a FlowEventBus bound to worker-local singletons if possible.

    Returns ``None`` if the flow store / DB are not available in this process,
    in which case event publishing will be a no-op.
    """
    try:
        from breadmind.flow.event_bus import FlowEventBus
        from breadmind.flow.store import FlowEventStore
        from breadmind.tasks import worker as worker_mod  # worker-local singletons
    except Exception as exc:  # pragma: no cover - import-time safety
        logger.debug("flow worker bus imports unavailable: %s", exc)
        return None

    db = getattr(worker_mod, "_db", None)
    if db is None:
        logger.debug("worker DB not initialized; flow events will not be published")
        return None

    try:
        store = FlowEventStore(db)
        return FlowEventBus(store=store, redis=getattr(worker_mod, "_redis_client", None))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("failed to construct FlowEventBus in worker: %s", exc)
        return None


async def _safe_publish(bus: Any, event: FlowEvent) -> None:
    if bus is None:
        return
    try:
        await bus.publish(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to publish %s for flow %s: %s",
            event.event_type.value,
            event.flow_id,
            exc,
        )


async def _run_tool(tool: str | None, args: dict[str, Any]) -> Any:
    """Execute ``tool`` via the worker-local ToolRegistry.

    Falls back to a ``{"skipped": True}`` placeholder when no tool is
    requested or when no registry is available in this process.
    """
    if not tool:
        return {"skipped": True, "reason": "no tool specified"}

    try:
        from breadmind.tasks import worker as worker_mod
    except Exception:  # pragma: no cover
        worker_mod = None  # type: ignore[assignment]

    registry = getattr(worker_mod, "_registry", None) if worker_mod else None
    if registry is None:
        logger.debug("worker ToolRegistry not initialized; skipping tool %r", tool)
        return {"skipped": True, "reason": "registry not initialized"}

    if hasattr(registry, "has_tool") and not registry.has_tool(tool):
        raise ValueError(f"tool {tool!r} not registered")

    result = await registry.execute(tool, args)
    # ``ToolResult`` is a dataclass; surface a JSON-friendly view.
    output = getattr(result, "output", None)
    success = getattr(result, "success", True)
    return {"success": success, "output": output}
