"""Celery task + beat registration tests."""
from __future__ import annotations

from breadmind.tasks.celery_app import celery_app


def test_kb_tasks_registered():
    names = set(celery_app.tasks.keys())
    assert "kb.review_daily_digest" in names
    assert "kb.extraction_nightly_personal" in names
    assert "kb.process_thread_resolved" in names


def test_beat_schedule_has_kb_entries():
    schedule = celery_app.conf.beat_schedule or {}
    task_names = {v["task"] for v in schedule.values()}
    assert "kb.review_daily_digest" in task_names
    assert "kb.extraction_nightly_personal" in task_names
