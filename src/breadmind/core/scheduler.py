import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    id: str
    name: str
    schedule: str  # cron expression: "0 9 * * 1" = every Monday 9AM
    task: str  # message to send to agent
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    model: str | None = None  # optional model override


@dataclass
class HeartbeatTask:
    id: str
    name: str
    interval_minutes: int = 30
    task: str = ""  # message/check to perform
    enabled: bool = True
    last_run: datetime | None = None
    run_count: int = 0


class Scheduler:
    """Cron job and heartbeat scheduler for BreadMind agent."""

    def __init__(self, message_handler: Callable = None):
        self._cron_jobs: dict[str, CronJob] = {}
        self._heartbeats: dict[str, HeartbeatTask] = {}
        self._message_handler = message_handler
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()

    async def start(self):
        if self._running:
            return
        self._running = True
        self._tasks.append(asyncio.create_task(self._cron_loop()))
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        logger.info("Scheduler started")

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Scheduler stopped")

    # --- Cron Jobs ---

    def add_cron_job(self, job: CronJob):
        self._cron_jobs[job.id] = job
        job.next_run = self._calc_next_run(job.schedule)

    def remove_cron_job(self, job_id: str) -> bool:
        return self._cron_jobs.pop(job_id, None) is not None

    def get_cron_jobs(self) -> list[dict]:
        return [
            {
                "id": j.id, "name": j.name, "schedule": j.schedule, "task": j.task,
                "enabled": j.enabled,
                "last_run": j.last_run.isoformat() if j.last_run else None,
                "next_run": j.next_run.isoformat() if j.next_run else None,
                "run_count": j.run_count, "model": j.model,
            }
            for j in self._cron_jobs.values()
        ]

    def enable_cron_job(self, job_id: str, enabled: bool):
        job = self._cron_jobs.get(job_id)
        if job:
            job.enabled = enabled

    # --- Heartbeats ---

    def add_heartbeat(self, hb: HeartbeatTask):
        self._heartbeats[hb.id] = hb

    def remove_heartbeat(self, hb_id: str) -> bool:
        return self._heartbeats.pop(hb_id, None) is not None

    def get_heartbeats(self) -> list[dict]:
        return [
            {
                "id": h.id, "name": h.name, "interval_minutes": h.interval_minutes,
                "task": h.task, "enabled": h.enabled,
                "last_run": h.last_run.isoformat() if h.last_run else None,
                "run_count": h.run_count,
            }
            for h in self._heartbeats.values()
        ]

    def enable_heartbeat(self, hb_id: str, enabled: bool):
        hb = self._heartbeats.get(hb_id)
        if hb:
            hb.enabled = enabled

    # --- Status ---

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "cron_jobs": len(self._cron_jobs),
            "heartbeats": len(self._heartbeats),
            "total_runs": (
                sum(j.run_count for j in self._cron_jobs.values())
                + sum(h.run_count for h in self._heartbeats.values())
            ),
        }

    # --- Internal loops ---

    async def _cron_loop(self):
        """Check and execute due cron jobs every 30 seconds."""
        while self._running:
            try:
                await asyncio.sleep(30)
                now = datetime.now(timezone.utc)
                for job in list(self._cron_jobs.values()):
                    if not job.enabled or not job.next_run:
                        continue
                    if now >= job.next_run:
                        await self._execute_job(job)
                        job.last_run = now
                        job.run_count += 1
                        job.next_run = self._calc_next_run(job.schedule)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cron loop error: {e}")

    async def _heartbeat_loop(self):
        """Check and execute due heartbeats."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute
                now = datetime.now(timezone.utc)
                for hb in list(self._heartbeats.values()):
                    if not hb.enabled:
                        continue
                    if hb.last_run is None or (now - hb.last_run).total_seconds() >= hb.interval_minutes * 60:
                        await self._execute_heartbeat(hb)
                        hb.last_run = now
                        hb.run_count += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")

    async def _execute_job(self, job: CronJob):
        """Execute a cron job by sending the task to the agent."""
        logger.info(f"Executing cron job: {job.name}")
        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    await self._message_handler(job.task, user="scheduler", channel="cron")
                else:
                    self._message_handler(job.task, user="scheduler", channel="cron")
            except Exception as e:
                logger.error(f"Cron job '{job.name}' failed: {e}")

    async def _execute_heartbeat(self, hb: HeartbeatTask):
        """Execute a heartbeat task."""
        logger.info(f"Executing heartbeat: {hb.name}")
        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    await self._message_handler(hb.task, user="scheduler", channel="heartbeat")
                else:
                    self._message_handler(hb.task, user="scheduler", channel="heartbeat")
            except Exception as e:
                logger.error(f"Heartbeat '{hb.name}' failed: {e}")

    def _calc_next_run(self, schedule: str) -> datetime | None:
        """Calculate next run time from a simple cron expression.
        Supports: minute hour day_of_month month day_of_week
        Uses simple parsing - not a full cron library."""
        try:
            parts = schedule.strip().split()
            if len(parts) != 5:
                return None
            now = datetime.now(timezone.utc)
            # Simple: for MVP, schedule next run at the specified time
            # Full cron parsing would need croniter library
            minute = int(parts[0]) if parts[0] != '*' else now.minute
            hour = int(parts[1]) if parts[1] != '*' else now.hour
            next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_dt <= now:
                next_dt += timedelta(days=1)
            return next_dt
        except Exception:
            return None
