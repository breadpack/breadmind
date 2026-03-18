"""Celery application instance for background jobs."""
from __future__ import annotations

import os

from celery import Celery

_redis_url = os.environ.get("BREADMIND_REDIS_URL", "redis://localhost:6379/0")

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
    imports=["breadmind.tasks.worker"],
)
