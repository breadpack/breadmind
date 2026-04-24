"""Celery entry points for coding-job maintenance.

Tasks:
    coding.cleanup_old_jobs  - retention sweep that deletes completed
                               coding jobs older than ``BREADMIND_JOBS_RETENTION_DAYS``
                               (default 90 days). Cascades drop phases
                               and phase logs via ON DELETE CASCADE FKs.

The ``coding.cleanup`` entry in ``celery_app.beat_schedule`` fires this
task once per day at 03:30 UTC. Running jobs (``finished_at IS NULL``)
are never touched — see ``JobStore.delete_old_jobs``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from breadmind.metrics import coding_jobs_deleted_total
from breadmind.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="coding.cleanup_old_jobs")
def cleanup_old_jobs() -> int:
    """Delete completed coding jobs older than the retention window.

    Returns the number of rows deleted so Beat / Flower surface the
    count in task results. Bumps ``coding_jobs_deleted_total`` so the
    Prometheus scrape endpoint reflects retention activity.
    """
    days = int(os.environ.get("BREADMIND_JOBS_RETENTION_DAYS", "90"))

    async def _run() -> int:
        from breadmind.coding.job_store import JobStore
        from breadmind.storage.database import Database

        dsn = os.environ.get("BREADMIND_DSN") or os.environ.get(
            "DATABASE_URL", ""
        )
        if not dsn:
            logger.warning(
                "coding.cleanup_old_jobs: no BREADMIND_DSN/DATABASE_URL; "
                "skipping retention sweep"
            )
            return 0

        db = Database(dsn)
        await db.connect()
        try:
            store = JobStore(db)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            return await store.delete_old_jobs(finished_before=cutoff)
        finally:
            await db.disconnect()

    n = asyncio.run(_run())
    logger.info(
        "coding.cleanup_old_jobs: deleted %d jobs older than %d days",
        n,
        days,
    )

    coding_jobs_deleted_total.inc(n)
    return n
