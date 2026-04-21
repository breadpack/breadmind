"""Periodic review queue digest + backpressure controller."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Spec §6.2: DM leads when >= 5 pending or daily trigger
_DM_THRESHOLD = 5
# Spec §8.1: pause extraction when backlog > 500
_BACKPRESSURE_LIMIT = 500


async def run_daily_digest(
    *,
    db: Any = None,
    slack_client: Any = None,
) -> dict[str, Any]:
    """Run once per day. For each project with pending reviews, DM the leads.

    Return shape: ``{"projects_dm": [...], "backpressure_projects": [...]}``.
    """
    # Resolve worker-local singletons when not passed explicitly
    if db is None or slack_client is None:
        from breadmind.tasks import worker as worker_mod
        db = db or getattr(worker_mod, "_db", None)
        slack_client = slack_client or getattr(worker_mod, "_slack_client", None)

    if db is None or slack_client is None:
        logger.warning("daily digest skipped - db or slack_client unavailable")
        return {"projects_dm": [], "backpressure_projects": []}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT project_id, COUNT(*) AS n_pending
            FROM promotion_candidates
            WHERE status IN ('pending', 'needs_edit')
            GROUP BY project_id
            """
        )

    projects_dm: list[str] = []
    backpressure: list[str] = []

    for r in rows:
        pid: UUID = r["project_id"]
        n = int(r["n_pending"])

        # DM leads if threshold met
        if n >= _DM_THRESHOLD:
            lead_ids = await _project_leads(db, pid)
            for uid in lead_ids:
                await _dm_lead(slack_client, uid, project_id=pid, n_pending=n)
            projects_dm.append(str(pid))

        # Backpressure: pause + warn
        if n > _BACKPRESSURE_LIMIT:
            await _pause_extraction(db, pid, reason=f"backlog {n} > {_BACKPRESSURE_LIMIT}")
            for uid in await _project_leads(db, pid):
                await _dm_lead_backpressure(slack_client, uid, project_id=pid, n_pending=n)
            backpressure.append(str(pid))

    # Publish the backlog gauge for ops dashboards (spec §8.4). This runs on
    # every daily digest pass so the metric stays reasonably fresh even if
    # nothing triggers DM/backpressure.
    try:
        from breadmind.kb.review_queue import ReviewQueue
        queue = ReviewQueue(db, slack_client)
        await queue.refresh_backlog_metric()
    except Exception:  # pragma: no cover — metrics must never break prod
        logger.exception("refresh_backlog_metric failed")

    return {"projects_dm": projects_dm, "backpressure_projects": backpressure}


async def _project_leads(db: Any, project_id: UUID) -> list[str]:
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id FROM org_project_members "
            "WHERE project_id=$1 AND role IN ('lead','admin')",
            project_id,
        )
    return [r["user_id"] for r in rows]


async def _dm_lead(
    slack_client: Any,
    user_id: str,
    *,
    project_id: UUID,
    n_pending: int,
) -> None:
    try:
        opened = await slack_client.conversations_open(users=user_id)
        channel = opened["channel"]["id"]
        text = (
            f":inbox_tray: *KB review digest* - {n_pending} candidate(s) awaiting "
            f"your review for project `{project_id}`.\n"
            f"Open: <https://breadmind.local/review?project={project_id}|review UI>"
        )
        await slack_client.chat_postMessage(channel=channel, text=text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lead digest DM failed for %s: %s", user_id, exc)


async def _dm_lead_backpressure(
    slack_client: Any,
    user_id: str,
    *,
    project_id: UUID,
    n_pending: int,
) -> None:
    try:
        opened = await slack_client.conversations_open(users=user_id)
        channel = opened["channel"]["id"]
        text = (
            f":warning: *Backpressure* - {n_pending} pending candidates for "
            f"`{project_id}`. New extraction is *paused* for this project until "
            f"the backlog is below {_BACKPRESSURE_LIMIT}."
        )
        await slack_client.chat_postMessage(channel=channel, text=text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("backpressure DM failed for %s: %s", user_id, exc)


async def _pause_extraction(db: Any, project_id: UUID, *, reason: str) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO kb_extraction_pause (project_id, paused, reason, paused_at)
            VALUES ($1, TRUE, $2, now())
            ON CONFLICT (project_id)
            DO UPDATE SET paused=TRUE, reason=EXCLUDED.reason, paused_at=now()
            """,
            project_id,
            reason,
        )


async def is_extraction_paused(db: Any, project_id: UUID) -> bool:
    async with db.acquire() as conn:
        paused = await conn.fetchval(
            "SELECT paused FROM kb_extraction_pause WHERE project_id=$1",
            project_id,
        )
    return bool(paused)
