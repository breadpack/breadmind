"""Flow list view: shows all flows for a user."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import UISpec, Component


async def build(db: Any, *, user_id: str) -> UISpec:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, status, updated_at
            FROM flows
            WHERE user_id = $1
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            user_id,
        )
    items: list[Component] = []
    for r in rows:
        items.append(Component(
            type="list",
            id=f"flow-item-{r['id']}",
            props={"variant": "flow_row"},
            children=[
                Component(type="heading", id=f"title-{r['id']}", props={"value": r["title"], "level": 4}),
                Component(type="badge", id=f"status-{r['id']}", props={
                    "value": r["status"],
                    "tone": _tone(r["status"]),
                }),
                Component(type="button", id=f"open-{r['id']}", props={
                    "label": "열기",
                    "action": {
                        "kind": "view_request",
                        "view_key": "flow_detail_view",
                        "params": {"flow_id": str(r["id"])},
                    },
                }),
            ],
        ))
    return UISpec(
        schema_version=1,
        root=Component(type="page", id="flow-list", props={"title": "내 Flows"}, children=[
            Component(type="heading", id="h", props={"value": "진행 중/완료된 작업", "level": 2}),
            Component(type="stack", id="stk", props={"gap": "md"}, children=items),
        ]),
    )


def _tone(status: str) -> str:
    return {
        "pending": "neutral",
        "running": "info",
        "paused": "warning",
        "escalated": "warning",
        "failed": "danger",
        "cancelled": "neutral",
        "completed": "success",
    }.get(status, "neutral")
