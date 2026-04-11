"""Flow detail view: DAG visualization + step cards."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from breadmind.sdui.spec import UISpec, Component


async def build(db: Any, *, flow_id: str) -> UISpec:
    try:
        uid = UUID(flow_id)
    except (ValueError, TypeError):
        return _not_found(flow_id)

    async with db.acquire() as conn:
        flow = await conn.fetchrow("SELECT * FROM flows WHERE id = $1", uid)
        steps = await conn.fetch(
            "SELECT * FROM flow_steps WHERE flow_id = $1 ORDER BY step_id",
            uid,
        )
    if flow is None:
        return _not_found(flow_id)

    nodes = [{"id": s["step_id"], "label": s["title"], "status": s["status"]} for s in steps]
    edges = []
    for s in steps:
        for dep in (s["depends_on"] or []):
            edges.append({"from": dep, "to": s["step_id"]})

    step_cards = [
        Component(type="step_card", id=f"sc-{s['step_id']}", props={
            "step_id": s["step_id"],
            "title": s["title"],
            "status": s["status"],
            "tool": s["tool"],
            "attempt": s["attempt"],
            "error": s["error"],
        })
        for s in steps
    ]

    return UISpec(
        schema_version=1,
        root=Component(type="page", id=f"flow-{flow_id}", props={"title": flow["title"]}, children=[
            Component(type="heading", id="h", props={"value": flow["title"], "level": 1}),
            Component(type="badge", id="status", props={"value": flow["status"], "tone": "info"}),
            Component(type="dag_view", id="dag", props={"nodes": nodes, "edges": edges}),
            Component(type="heading", id="h2", props={"value": "단계", "level": 3}),
            Component(type="stack", id="cards", props={"gap": "sm"}, children=step_cards),
        ]),
    )


def _not_found(flow_id: str) -> UISpec:
    return UISpec(
        schema_version=1,
        root=Component(type="page", id="missing", props={"title": "Not found"}, children=[
            Component(type="heading", id="h", props={"value": "Flow not found", "level": 2}),
            Component(type="text", id="t", props={"value": f"No flow with id {flow_id}"}),
        ]),
    )
