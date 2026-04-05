"""Built-in cron/scheduling engine for BreadMind."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from breadmind.utils.helpers import cancel_task_safely, generate_short_id

logger = logging.getLogger(__name__)


class ScheduleType(str, Enum):
    AT = "at"        # One-shot (ISO 8601 or relative like "20m")
    EVERY = "every"  # Fixed interval
    CRON = "cron"    # 5-field cron expression


class JobStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CronJob:
    id: str
    name: str
    schedule_type: ScheduleType
    schedule: str  # "20m", "5m", "*/5 * * * *"
    handler: Callable[..., Awaitable[Any]]
    args: dict = field(default_factory=dict)
    status: JobStatus = JobStatus.ACTIVE
    max_retries: int = 3
    retry_count: int = 0
    last_run: float = 0
    next_run: float = 0
    created_at: float = field(default_factory=time.time)


class CronEngine:
    """Lightweight in-process cron engine."""

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def add_job(
        self,
        name: str,
        schedule_type: ScheduleType,
        schedule: str,
        handler: Callable,
        args: dict | None = None,
    ) -> CronJob:
        job_id = f"cron_{generate_short_id()}"
        job = CronJob(
            id=job_id,
            name=name,
            schedule_type=schedule_type,
            schedule=schedule,
            handler=handler,
            args=args or {},
        )
        job.next_run = self._calculate_next_run(job)
        self._jobs[job_id] = job
        return job

    def remove_job(self, job_id: str) -> bool:
        return self._jobs.pop(job_id, None) is not None

    def pause_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.PAUSED
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.ACTIVE
            job.next_run = self._calculate_next_run(job)
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        await cancel_task_safely(self._task)

    async def _run_loop(self) -> None:
        while self._running:
            now = time.time()
            for job in list(self._jobs.values()):
                if job.status != JobStatus.ACTIVE:
                    continue
                if now >= job.next_run:
                    asyncio.create_task(self._execute_job(job))
            await asyncio.sleep(1)

    async def _execute_job(self, job: CronJob) -> None:
        job.last_run = time.time()
        try:
            await job.handler(**job.args)
            job.retry_count = 0
            if job.schedule_type == ScheduleType.AT:
                job.status = JobStatus.COMPLETED
            else:
                job.next_run = self._calculate_next_run(job)
        except Exception as e:
            logger.error("Cron job %s failed: %s", job.name, e)
            job.retry_count += 1
            if job.retry_count >= job.max_retries:
                job.status = JobStatus.FAILED
            else:
                # Exponential backoff: 60s, 120s, 300s
                delays = [60, 120, 300]
                delay = delays[min(job.retry_count - 1, len(delays) - 1)]
                job.next_run = time.time() + delay

    def _calculate_next_run(self, job: CronJob) -> float:
        now = time.time()
        if job.schedule_type == ScheduleType.AT:
            return now + self._parse_duration(job.schedule)
        elif job.schedule_type == ScheduleType.EVERY:
            return now + self._parse_duration(job.schedule)
        elif job.schedule_type == ScheduleType.CRON:
            return now + 60  # simplified: check every minute
        return now + 60

    @staticmethod
    def _parse_duration(s: str) -> float:
        """Parse duration strings like '20m', '1h', '30s', '2d'."""
        m = re.match(r'^(\d+)([smhd])$', s.strip())
        if not m:
            return 60  # default 1 minute
        val, unit = int(m.group(1)), m.group(2)
        multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
        return val * multipliers.get(unit, 60)
