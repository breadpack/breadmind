"""Coding jobs view: list jobs with progress and cancel actions.

Two schema flavours live here:

* ``build(db, job_tracker=...)`` — async, returns a :class:`UISpec` tree.
  Used by the SDUI projector / WebSocket ``/ws/ui`` channel.
* ``build_list_screen(...)`` — sync, returns a flat dict schema with
  ``Active`` / ``Recent`` sections. Used by the HTTP ``/coding-jobs``
  page route (Task 16) so non-WebSocket clients (e.g. plain browser
  navigation, curl probes) can render the same list.
"""
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


# ── Task 16: flat dict schema for HTTP /coding-jobs page ─────────────────────


def _row(j: dict[str, Any]) -> dict[str, Any]:
    """Project a ``JobInfo.to_dict()`` payload into a compact list row.

    All job-originated fields use ``.get(...)`` with defaults so the row
    still renders cleanly if upstream drops a key (e.g. older serialized
    rows missing ``total_phases``).
    """
    total = j.get("total_phases", 0)
    done = j.get("completed_phases", 0)
    pct = j.get("progress_pct", 0)
    prompt = j.get("prompt", "") or ""
    return {
        "type": "job_row",
        "id": j["job_id"],
        "status": j["status"],
        "project": j.get("project", ""),
        "prompt": prompt[:80],
        "progress": f"{done}/{total} ({pct}%)",
        "user": j.get("user", ""),
        "started_at": j.get("started_at", 0),
        "link": f"/coding-jobs/{j['job_id']}",
    }


def build_list_screen(
    *,
    active_jobs: list[dict[str, Any]],
    recent_jobs: list[dict[str, Any]],
    current_username: str,
    is_admin: bool,
    mine: bool,
) -> dict[str, Any]:
    """Build the flat list-screen schema used by ``GET /coding-jobs``.

    The shape is intentionally JSON-serialisable without going through
    :class:`UISpec`: this page is rendered by a thin HTTP client, not the
    WebSocket projector. The ``ws_subscribe`` list tells clients which
    ``/ws/ui`` frame types to listen on for live refresh.
    """
    return {
        "type": "screen",
        "title": "Coding Jobs",
        "header": {
            "filters": [
                {
                    "type": "toggle",
                    "key": "mine",
                    "label": "My jobs only",
                    "value": bool(mine),
                    # Admins get the toggle OFF by default (they see all),
                    # while non-admins are forced to mine=1 server-side.
                    "admin_default_off": is_admin,
                },
                {
                    "type": "select",
                    "key": "status",
                    "label": "Status",
                    "options": [
                        "all", "running", "completed", "failed", "cancelled",
                    ],
                    "value": "all",
                },
            ],
            "current_user": current_username,
            "is_admin": is_admin,
        },
        "sections": [
            {
                "title": "Active",
                "items": [_row(j) for j in active_jobs],
                "empty_text": "활성 작업이 없습니다.",
            },
            {
                "title": "Recent",
                "items": [_row(j) for j in recent_jobs],
                "empty_text": "최근 작업이 없습니다.",
            },
        ],
        "ws_subscribe": [
            "coding_job_created",
            "coding_job_running",
            "coding_job_completed",
            "coding_job_cancelled",
            "phase_started",
            "phase_completed",
        ],
    }


# ── Task 17: flat dict schema for HTTP /coding-jobs/{job_id} page ────────────


_CANCELLABLE_STATUSES = ("pending", "decomposing", "running")


def build_detail_screen(
    *,
    job: dict[str, Any],
    can_cancel: bool,
    selected_step: int | None = None,
) -> dict[str, Any]:
    """Build the flat detail-screen schema used by ``GET /coding-jobs/{job_id}``.

    Parameters
    ----------
    job:
        A :meth:`JobInfo.to_dict` payload. Must carry ``job_id``, ``status``,
        ``project``, ``agent``, ``prompt``, phase counters, and a ``phases``
        list where each entry has ``step``, ``title``, ``status``,
        ``duration_seconds``, and ``files_changed``.
    can_cancel:
        The authz verdict from the route — ``True`` when the caller is the
        job owner or an admin. The button is still hidden for terminal-status
        jobs even when this is ``True``.
    selected_step:
        Which phase the log panel should tail. When ``None`` (the default for
        route callers not echoing a query param) we pick the running phase,
        falling back to the first phase if none is running.

    The shape mirrors :func:`build_list_screen` (flat JSON, not a
    :class:`UISpec`) so the same thin HTTP client that renders the list page
    can render the detail page without going through the WebSocket projector.
    """
    phases = job.get("phases", [])
    if selected_step is None:
        running_phase = next(
            (p for p in phases if p.get("status") == "running"), None
        )
        if running_phase is not None:
            selected_step = running_phase["step"]
        elif phases:
            selected_step = phases[0]["step"]
        else:
            selected_step = 1

    job_id = job["job_id"]
    return {
        "type": "screen",
        "title": f"Job {job_id}",
        "header": {
            "project": job.get("project", ""),
            "agent": job.get("agent", ""),
            "user": job.get("user", ""),
            "status": job["status"],
            "duration_seconds": job.get("duration_seconds", 0),
            "progress_pct": job.get("progress_pct", 0),
            "total_phases": job.get("total_phases", 0),
            "completed_phases": job.get("completed_phases", 0),
        },
        "phases": [
            {
                "step": p["step"],
                "title": p["title"],
                "status": p["status"],
                "duration_seconds": p.get("duration_seconds", 0),
                "files_changed_count": len(p.get("files_changed", [])),
                "files_changed": p.get("files_changed", []),
            }
            for p in phases
        ],
        "log_panel": {
            "selected_step": selected_step,
            "fetch_url": (
                f"/api/coding-jobs/{job_id}/phases/{selected_step}/logs"
            ),
            "ws_event": "coding_phase_log",
            "autoscroll": True,
        },
        "cancel_button": {
            "visible": (
                bool(can_cancel) and job["status"] in _CANCELLABLE_STATUSES
            ),
            "action_url": f"/api/coding-jobs/{job_id}/cancel",
            "confirm_text": (
                "이 job을 취소하시겠습니까? 실행 중인 Phase가 중단됩니다."
            ),
        },
    }
