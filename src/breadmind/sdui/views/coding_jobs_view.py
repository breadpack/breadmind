"""Coding jobs view: list jobs with progress and cancel actions."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import UISpec, Component


_STATUS_TONE = {
    "pending": "neutral",
    "running": "info",
    "completed": "success",
    "failed": "danger",
    "cancelled": "neutral",
}


async def build(db: Any, *, job_tracker: Any = None, **_kwargs: Any) -> UISpec:
    jobs = await _safe_list_jobs(job_tracker)

    if not jobs:
        body = Component(type="text", id="empty", props={"value": "활성 코딩 작업이 없습니다."})
    else:
        body = Component(
            type="stack",
            id="jobs",
            props={"gap": "md"},
            children=[_job_card(j) for j in jobs],
        )

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="coding-jobs",
            props={"title": "코딩 작업"},
            children=[
                Component(type="heading", id="h", props={"value": "코딩 작업", "level": 2}),
                Component(type="text", id="count", props={"value": f"총 {len(jobs)}개"}),
                body,
            ],
        ),
    )


def _job_card(j: dict) -> Component:
    jid = str(j.get("id", "unknown"))
    status = j.get("status", "unknown")
    progress = j.get("progress") or {}
    pct = progress.get("percentage") or 0
    message = progress.get("message") or ""
    title = j.get("project") or jid

    children = [
        Component(type="heading", id=f"jt-{jid}", props={"value": title, "level": 4}),
        Component(
            type="badge",
            id=f"js-{jid}",
            props={
                "value": status,
                "tone": _STATUS_TONE.get(status, "neutral"),
            },
        ),
    ]

    desc = j.get("description") or ""
    if desc:
        children.append(Component(type="text", id=f"jd-{jid}", props={"value": desc}))

    if isinstance(pct, (int, float)) and pct > 0:
        children.append(
            Component(type="progress", id=f"jp-{jid}", props={"value": float(pct)})
        )
    if message:
        children.append(Component(type="text", id=f"jm-{jid}", props={"value": message}))

    children.append(
        Component(
            type="kv",
            id=f"jk-{jid}",
            props={
                "items": [
                    {"key": "ID", "value": jid},
                    {"key": "유형", "value": str(j.get("job_type", "?"))},
                    {"key": "플랫폼", "value": str(j.get("platform", "?"))},
                    {
                        "key": "단계",
                        "value": ", ".join(_phase_names(j.get("phases"))) or "?",
                    },
                ],
            },
        )
    )

    err = j.get("error")
    if err:
        children.append(
            Component(type="text", id=f"je-{jid}", props={"value": f"오류: {err}"})
        )

    if status in ("running", "pending"):
        children.append(
            Component(
                type="button",
                id=f"jc-{jid}",
                props={
                    "label": "취소",
                    "variant": "ghost",
                    "action": {
                        "kind": "intervention",
                        "category": "coding_job",
                        "operation": "cancel",
                        "job_id": jid,
                    },
                },
            )
        )

    return Component(
        type="list",
        id=f"job-{jid}",
        props={"variant": "coding_job"},
        children=children,
    )


def _phase_names(phases: Any) -> list[str]:
    if not phases:
        return []
    out: list[str] = []
    for p in phases:
        if isinstance(p, dict):
            name = p.get("name") or p.get("title") or p.get("id")
            if name:
                out.append(str(name))
        else:
            out.append(str(p))
    return out


async def _safe_list_jobs(tracker: Any) -> list[dict]:
    if tracker is None:
        return []
    try:
        for attr in ("list_jobs", "list_all", "get_all", "jobs", "all_jobs", "to_list"):
            if hasattr(tracker, attr):
                obj = getattr(tracker, attr)
                result = obj() if callable(obj) else obj
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, dict):
                    result = list(result.values())
                return [_normalize(j) for j in result]
    except Exception:
        return []
    return []


def _normalize(j: Any) -> dict:
    if isinstance(j, dict):
        return j
    # Dataclass / JobInfo — prefer to_dict() if available
    if hasattr(j, "to_dict") and callable(j.to_dict):
        try:
            d = j.to_dict()
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {
        "id": getattr(j, "id", None),
        "status": getattr(j, "status", None),
        "project": getattr(j, "project", None),
        "job_type": getattr(j, "job_type", None),
        "platform": getattr(j, "platform", None),
        "phases": getattr(j, "phases", None),
        "progress": getattr(j, "progress", None),
        "error": getattr(j, "error", None),
        "description": getattr(j, "description", None),
    }
