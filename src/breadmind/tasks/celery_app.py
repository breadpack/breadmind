"""Celery application instance for background jobs."""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

from breadmind.constants import DEFAULT_REDIS_URL

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
    },
)

# Eagerly import task modules so that task decorators run and populate
# ``celery_app.tasks`` whenever the app object is imported (not just when a
# Celery worker boots and calls ``loader.import_default_modules()``).
# This keeps tests, beat schedule introspection, and ad-hoc imports all
# seeing the same registry.
celery_app.loader.import_default_modules()
