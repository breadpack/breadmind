"""Monitoring events view: lists recent monitoring events with severity filter."""
from __future__ import annotations

import logging
from typing import Any

from breadmind.sdui.spec import Component, UISpec

logger = logging.getLogger(__name__)

_SEVERITY_LABELS: dict[str, str] = {
    "all": "전체",
    "critical": "심각",
    "warning": "경고",
    "info": "정보",
}

_SEVERITY_SYMBOL: dict[str, str] = {
    "critical": "[CRIT]",
    "warning": "[WARN]",
    "info": "[INFO]",
}

_TABLE_NAME = "monitoring_events"


async def build(db: Any, *, severity: str = "all", **_kwargs: Any) -> UISpec:
    """Build the monitoring view UISpec.

    Queries recent monitoring events from the DB. If the monitoring_events
    table does not exist yet (monitoring persistence not yet wired), the
    view gracefully degrades to an empty list rather than erroring.
    """
    severity = severity if severity in _SEVERITY_LABELS else "all"

    rows: list[dict[str, Any]] = []
    try:
        async with db.acquire() as conn:
            if severity == "all":
                fetched = await conn.fetch(
                    f"""
                    SELECT timestamp, severity, source, target, condition, details, message
                    FROM {_TABLE_NAME}
                    ORDER BY timestamp DESC
                    LIMIT 100
                    """
                )
            else:
                fetched = await conn.fetch(
                    f"""
                    SELECT timestamp, severity, source, target, condition, details, message
                    FROM {_TABLE_NAME}
                    WHERE severity = $1
                    ORDER BY timestamp DESC
                    LIMIT 100
                    """,
                    severity,
                )
            rows = [dict(r) for r in fetched]
    except Exception as exc:  # noqa: BLE001
        # Table may not exist yet or columns may differ — degrade gracefully.
        logger.debug("monitoring_view: falling back to empty rows (%s)", exc)
        rows = []

    columns = ["시각", "심각도", "소스", "대상", "메시지"]
    table_rows: list[list[str]] = []
    for r in rows:
        ts = r.get("timestamp")
        ts_text = ts.strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""
        sev = (r.get("severity") or "").lower()
        sev_text = _SEVERITY_SYMBOL.get(sev, f"[{sev.upper()}]" if sev else "")
        message = r.get("message") or r.get("condition") or ""
        table_rows.append([
            ts_text,
            sev_text,
            r.get("source") or "",
            r.get("target") or "",
            str(message)[:200],
        ])

    filter_buttons: list[Component] = [
        Component(
            type="button",
            id=f"filter-{s}",
            props={
                "label": label,
                "variant": "primary" if s == severity else "ghost",
                "action": {
                    "kind": "view_request",
                    "view_key": "monitoring_view",
                    "params": {"severity": s},
                },
            },
        )
        for s, label in _SEVERITY_LABELS.items()
    ]

    empty_text = "이벤트가 없습니다." if not table_rows else ""

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="monitoring",
            props={"title": "모니터링"},
            children=[
                Component(
                    type="heading",
                    id="h",
                    props={"value": "모니터링 이벤트", "level": 2},
                ),
                Component(
                    type="stack",
                    id="filters",
                    props={"gap": "sm"},
                    children=filter_buttons,
                ),
                Component(
                    type="table",
                    id="events",
                    props={"columns": columns, "rows": table_rows},
                ),
                Component(
                    type="text",
                    id="empty",
                    props={"value": empty_text},
                ),
            ],
        ),
    )
