"""Celery application instance for background jobs."""
from __future__ import annotations

import asyncio
import logging
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init

from breadmind.constants import DEFAULT_REDIS_URL

logger = logging.getLogger(__name__)

_redis_url = os.environ.get("BREADMIND_REDIS_URL", DEFAULT_REDIS_URL)

celery_app = Celery(
    "breadmind",
    broker=_redis_url,
    backend=_redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    imports=[
        "breadmind.tasks.worker",
        "breadmind.tasks.kb_tasks",
        "breadmind.tasks.coding_tasks",
        "breadmind.kb.connectors.schedule",
        "breadmind.kb.quality_eval",
    ],
    beat_schedule={
        "kb-review-daily-digest": {
            "task": "kb.review_daily_digest",
            "schedule": crontab(hour=9, minute=0),   # daily 09:00 UTC
        },
        "kb-extraction-nightly-personal": {
            "task": "kb.extraction_nightly_personal",
            "schedule": crontab(hour=2, minute=30),  # nightly 02:30 UTC
        },
        "kb-weekly-quality-eval": {
            "task": "breadmind.kb.quality_eval.weekly",
            "schedule": crontab(hour=3, minute=0, day_of_week=1),  # Mon 03:00 UTC
        },
        "coding.cleanup": {
            "task": "coding.cleanup_old_jobs",
            "schedule": crontab(hour=3, minute=30),  # daily 03:30 UTC
        },
    },
)


# ── Beat startup: reload connector schedule from DB ─────────────────────
#
# ``reload_beat_schedule_from_db`` is otherwise only invoked on
# ``/api/connectors`` writes. Without this handler, every Beat restart
# would run with an empty confluence schedule until the next admin write.
# Wiring it to ``beat_init`` gives Beat an up-to-date schedule at boot.


@beat_init.connect
def _reload_connector_schedule_on_beat_init(sender=None, **kwargs):  # pragma: no cover - signal boot path
    """Pull the current confluence connector schedule from Postgres.

    This runs once inside the Beat process just before the scheduler
    starts ticking. Failures are logged but never raised — Beat should
    keep running with whatever schedule is already installed rather
    than crash-loop on a transient DB blip.
    """
    dsn = os.environ.get("BREADMIND_DSN") or os.environ.get("DATABASE_URL", "")
    if not dsn:
        logger.warning(
            "beat_init: no BREADMIND_DSN/DATABASE_URL; skipping "
            "connector schedule reload",
        )
        return

    try:
        from breadmind.kb.connectors.schedule import reload_beat_schedule_from_db
        from breadmind.storage.database import Database

        async def _run() -> None:
            db = Database(dsn)
            await db.connect()
            try:
                await reload_beat_schedule_from_db(db)
            finally:
                await db.disconnect()

        asyncio.run(_run())
    except Exception:  # noqa: BLE001 — best effort
        logger.exception(
            "beat_init: failed to reload connector schedule from DB",
        )


# Eagerly import task modules so that task decorators run and populate
# ``celery_app.tasks`` whenever the app object is imported (not just when a
# Celery worker boots and calls ``loader.import_default_modules()``).
# This keeps tests, beat schedule introspection, and ad-hoc imports all
# seeing the same registry.
celery_app.loader.import_default_modules()
