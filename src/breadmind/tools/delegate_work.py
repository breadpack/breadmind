"""delegate_work builtin tool: hands a natural-language task to the Flow system.

The core :func:`delegate_work_impl` is a pure async function that the
CoreAgent-facing builtin tool wrapper can invoke once it has resolved the
runtime bus and generator. Keeping the impl separate from the decorator
registered tool keeps it trivial to unit-test without spinning up a runtime.

The thin :func:`delegate_work` wrapper is registered through the usual
``@tool`` decorator and relies on module-level dependency injection via
:func:`set_flow_runtime` (mirroring how ``run_background`` resolves its
:class:`BackgroundJobManager`). Wiring those dependencies is Task 14's job;
until then the wrapper returns a clear error string so the agent can fall
back gracefully.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.events import EventType, FlowActor, FlowEvent
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


async def delegate_work_impl(
    *,
    title: str,
    description: str,
    user_id: str,
    bus: FlowEventBus,
    dag_generator: Any,
    available_tools: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new flow and propose its initial DAG.

    Emits a ``FLOW_CREATED`` event, asks ``dag_generator`` to produce an
    initial plan, then emits ``DAG_PROPOSED``. The ``seq`` field on each
    event is assigned by the store on append, so a sentinel value of ``0``
    is fine here.
    """
    flow_id = uuid4()

    await bus.publish(
        FlowEvent(
            flow_id=flow_id,
            seq=0,
            event_type=EventType.FLOW_CREATED,
            payload={
                "title": title,
                "description": description,
                "user_id": user_id,
                "origin": "chat",
                "metadata": metadata or {},
            },
            actor=FlowActor.AGENT,
        )
    )

    dag = await dag_generator.generate(
        title=title,
        description=description,
        available_tools=available_tools,
    )

    await bus.publish(
        FlowEvent(
            flow_id=flow_id,
            seq=0,
            event_type=EventType.DAG_PROPOSED,
            payload={"steps": dag.to_payload()},
            actor=FlowActor.AGENT,
        )
    )

    return {
        "flow_id": str(flow_id),
        "initial_dag_summary": {
            "step_count": len(dag.steps),
            "titles": [s.title for s in dag.steps],
        },
    }


# ---------------------------------------------------------------------------
# Runtime DI + builtin tool wrapper
# ---------------------------------------------------------------------------

_flow_bus: FlowEventBus | None = None
_dag_generator: Any | None = None
_available_tools_provider: Any | None = None
_default_user_id: str = "system"


def set_flow_runtime(
    *,
    bus: FlowEventBus | None,
    dag_generator: Any | None,
    available_tools_provider: Any | None = None,
    default_user_id: str = "system",
) -> None:
    """Inject the flow runtime dependencies used by the ``delegate_work`` tool.

    ``available_tools_provider`` is an optional zero-arg callable returning
    a list of tool names visible to the flow planner. If not supplied the
    wrapper falls back to an empty list.
    """
    global _flow_bus, _dag_generator, _available_tools_provider, _default_user_id
    _flow_bus = bus
    _dag_generator = dag_generator
    _available_tools_provider = available_tools_provider
    _default_user_id = default_user_id


@tool(
    description=(
        "Delegate a complex, long-running task to the Durable Task Flow "
        "system. Provide a short 'title' and a natural-language "
        "'description' of the work. The Flow system will plan, execute, "
        "and recover the task asynchronously. Returns the flow id and a "
        "summary of the proposed plan."
    )
)
async def delegate_work(title: str, description: str, user_id: str = "") -> dict[str, Any]:
    if _flow_bus is None or _dag_generator is None:
        return {
            "error": (
                "Flow runtime is not initialized on this agent. "
                "delegate_work cannot route tasks until the flow event bus "
                "and DAG generator are wired up."
            )
        }

    tools = list(_available_tools_provider()) if callable(_available_tools_provider) else []
    try:
        return await delegate_work_impl(
            title=title,
            description=description,
            user_id=user_id or _default_user_id,
            bus=_flow_bus,
            dag_generator=_dag_generator,
            available_tools=tools,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("delegate_work failed")
        return {"error": f"delegate_work failed: {exc}"}
