"""In-session recurring prompt execution (/loop command)."""
from __future__ import annotations
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

@dataclass
class LoopJob:
    id: str
    prompt: str
    interval_seconds: float
    handler: Callable[[str], Awaitable[str]]
    running: bool = True
    run_count: int = 0
    last_result: str = ""
    created_at: float = field(default_factory=time.time)

class LoopRunner:
    """Manages recurring prompt execution within a session."""

    def __init__(self) -> None:
        self._jobs: dict[str, LoopJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._counter = 0

    def start_loop(self, prompt: str, interval: str,
                   handler: Callable[[str], Awaitable[str]]) -> LoopJob:
        """Start a recurring prompt. interval: '5m', '1h', '30s', etc."""
        self._counter += 1
        job_id = f"loop_{self._counter}"
        seconds = self._parse_interval(interval)

        job = LoopJob(
            id=job_id, prompt=prompt,
            interval_seconds=seconds, handler=handler,
        )
        self._jobs[job_id] = job
        self._tasks[job_id] = asyncio.create_task(self._run_loop(job))
        logger.info("Started loop %s: '%s' every %ds", job_id, prompt[:50], seconds)
        return job

    def stop_loop(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.running = False
        task = self._tasks.get(job_id)
        if task:
            task.cancel()
        return True

    def stop_all(self) -> int:
        count = 0
        for job_id in list(self._jobs.keys()):
            if self.stop_loop(job_id):
                count += 1
        return count

    def list_loops(self) -> list[dict]:
        return [
            {"id": j.id, "prompt": j.prompt[:80], "interval": j.interval_seconds,
             "running": j.running, "run_count": j.run_count,
             "last_result": j.last_result[:200]}
            for j in self._jobs.values()
        ]

    async def _run_loop(self, job: LoopJob) -> None:
        # Wait for first interval before first run
        await asyncio.sleep(job.interval_seconds)
        while job.running:
            try:
                result = await job.handler(job.prompt)
                job.last_result = result
                job.run_count += 1
            except Exception as e:
                job.last_result = f"Error: {e}"
                logger.error("Loop %s error: %s", job.id, e)
            await asyncio.sleep(job.interval_seconds)

    @staticmethod
    def _parse_interval(s: str) -> float:
        m = re.match(r'^(\d+)([smhd])$', s.strip())
        if not m:
            return 600  # default 10 minutes
        val, unit = int(m.group(1)), m.group(2)
        return val * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unit]
