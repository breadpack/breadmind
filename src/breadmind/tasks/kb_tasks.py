"""Celery entry points for the KB P3 knowledge pipeline.

Tasks:
    kb.review_daily_digest          - daily per-project lead digest DM
    kb.extraction_nightly_personal  - extract candidates from the last 24h of
                                      episodic memory across all users
    kb.process_thread_resolved      - extract from a resolved Slack thread
"""
from __future__ import annotations

import asyncio
import logging

from breadmind.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="kb.review_daily_digest")
def review_daily_digest_task() -> dict:
    from breadmind.kb.review_dispatcher import run_daily_digest
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_daily_digest())
    finally:
        loop.close()


@celery_app.task(name="kb.extraction_nightly_personal")
def extraction_nightly_personal_task() -> dict:
    from breadmind.kb.extraction_triggers import run_personal_nightly
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_personal_nightly())
    finally:
        loop.close()


@celery_app.task(name="kb.process_thread_resolved")
def process_thread_resolved_task(
    channel_id: str,
    thread_ts: str,
    project_id: str,
) -> dict:
    from breadmind.kb.extraction_triggers import process_thread_resolved
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            process_thread_resolved(channel_id, thread_ts, project_id)
        )
    finally:
        loop.close()
