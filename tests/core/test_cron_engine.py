"""Tests for the built-in cron/scheduling engine."""
from __future__ import annotations

import asyncio
import time

import pytest

from breadmind.core.cron_engine import (
    CronEngine,
    CronJob,
    JobStatus,
    ScheduleType,
)


@pytest.fixture
def engine() -> CronEngine:
    return CronEngine()


async def _noop(**kwargs):
    pass


async def _failing(**kwargs):
    raise RuntimeError("boom")


async def test_add_job(engine: CronEngine):
    job = engine.add_job("test", ScheduleType.EVERY, "5m", _noop)
    assert job.name == "test"
    assert job.id.startswith("cron_")
    assert job.status == JobStatus.ACTIVE
    assert job.schedule_type == ScheduleType.EVERY
    assert job.schedule == "5m"
    assert job.next_run > 0


async def test_remove_job(engine: CronEngine):
    job = engine.add_job("test", ScheduleType.EVERY, "5m", _noop)
    assert engine.remove_job(job.id) is True
    assert engine.remove_job(job.id) is False
    assert len(engine.list_jobs()) == 0


async def test_pause_resume(engine: CronEngine):
    job = engine.add_job("test", ScheduleType.EVERY, "5m", _noop)
    assert engine.pause_job(job.id) is True
    assert job.status == JobStatus.PAUSED

    assert engine.resume_job(job.id) is True
    assert job.status == JobStatus.ACTIVE

    # Non-existent job
    assert engine.pause_job("nonexistent") is False
    assert engine.resume_job("nonexistent") is False


async def test_parse_duration_minutes(engine: CronEngine):
    assert engine._parse_duration("20m") == 1200.0


async def test_parse_duration_hours(engine: CronEngine):
    assert engine._parse_duration("1h") == 3600.0


async def test_parse_duration_seconds(engine: CronEngine):
    assert engine._parse_duration("30s") == 30.0


async def test_one_shot_completes_after_run(engine: CronEngine):
    job = engine.add_job("oneshot", ScheduleType.AT, "1s", _noop)
    # Simulate execution
    await engine._execute_job(job)
    assert job.status == JobStatus.COMPLETED


async def test_retry_on_failure(engine: CronEngine):
    job = engine.add_job("failing", ScheduleType.EVERY, "5m", _failing)
    await engine._execute_job(job)
    assert job.retry_count == 1
    assert job.status == JobStatus.ACTIVE


async def test_max_retries_marks_failed(engine: CronEngine):
    job = engine.add_job("failing", ScheduleType.EVERY, "5m", _failing)
    job.max_retries = 2
    await engine._execute_job(job)
    assert job.retry_count == 1
    assert job.status == JobStatus.ACTIVE
    await engine._execute_job(job)
    assert job.retry_count == 2
    assert job.status == JobStatus.FAILED


async def test_list_jobs(engine: CronEngine):
    engine.add_job("a", ScheduleType.EVERY, "1m", _noop)
    engine.add_job("b", ScheduleType.EVERY, "2m", _noop)
    jobs = engine.list_jobs()
    assert len(jobs) == 2
    names = {j.name for j in jobs}
    assert names == {"a", "b"}


async def test_start_stop(engine: CronEngine):
    await engine.start()
    assert engine._running is True
    assert engine._task is not None
    await engine.stop()
    assert engine._running is False
