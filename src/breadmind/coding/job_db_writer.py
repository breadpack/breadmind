"""DB write-through serializer for JobTracker (extracted from job_tracker.py).

Single FIFO queue + single worker preserves the ordering guarantee that
prevents `status='running'` from committing after `status='completed'`
under asyncpg pool max_size > 1. Phase 2 adds bounded queue + drop_newest;
Phase 3 promotes the single (queue, worker) pair to a per-loop dict.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Coroutine

from breadmind.coding.job_models import JobInfo, PhaseInfo, PhaseStatus
from breadmind.metrics import coding_db_writer_drops_total

logger = logging.getLogger(__name__)


def _utc(ts: float) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class JobDbWriter:
    """Best-effort DB write-through for JobTracker state mutations."""

    def __init__(
        self,
        store: Any,
        *,
        max_queue_size: int | None = None,
    ) -> None:
        self._store = store
        self._max_queue_size = max_queue_size or int(
            os.getenv("BREADMIND_CODING_DB_QUEUE_MAX", "2000")
        )
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None

    # ── Scheduling ──────────────────────────────────────────────────────

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            coding_db_writer_drops_total.labels(reason="no_loop").inc()
            return
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._max_queue_size)
        if self._worker is None or self._worker.done():
            self._worker = loop.create_task(self._worker_loop())
        if self._queue.full():
            coro.close()
            coding_db_writer_drops_total.labels(reason="queue_full").inc()
            return
        self._queue.put_nowait(coro)

    async def _worker_loop(self) -> None:
        assert self._queue is not None
        while True:
            coro = await self._queue.get()
            try:
                await coro
            except Exception as exc:
                logger.warning("JobDbWriter coro failed: %s", exc)
                coding_db_writer_drops_total.labels(reason="coro_failed").inc()
            finally:
                self._queue.task_done()

    async def join(self) -> None:
        """Wait until the queue drains. Used by JobLogStream.append."""
        if self._queue is not None:
            await self._queue.join()

    # ── Helpers (one method per JobTracker mutation) ────────────────────

    def insert_job(self, job: JobInfo) -> None:
        if self._store is None:
            return
        started_at = _utc(job.started_at) or datetime.now(timezone.utc)
        self.schedule(self._store.insert_job(
            job_id=job.job_id,
            project=job.project,
            agent=job.agent,
            prompt=job.prompt,
            user_name=job.user,
            channel=job.channel,
            started_at=started_at,
            status=job.status.value,
        ))

    def update_job_status(self, job: JobInfo) -> None:
        self.schedule(self._store.update_job(
            job_id=job.job_id,
            status=job.status.value,
        ))

    def insert_phases(self, job_id: str, phases: list[PhaseInfo]) -> None:
        payload = [{"step": p.step, "title": p.title} for p in phases]
        self.schedule(self._store.insert_phases(job_id, payload))

    def update_job_total_phases(self, job: JobInfo) -> None:
        self.schedule(self._store.update_job(
            job_id=job.job_id,
            status=job.status.value,
            total_phases=job.total_phases,
        ))

    def update_phase_started(self, job_id: str, phase: PhaseInfo) -> None:
        self.schedule(self._store.update_phase(
            job_id=job_id,
            step=phase.step,
            status=PhaseStatus.RUNNING.value,
            started_at=_utc(phase.started_at),
        ))

    def update_phase_finished(self, job_id: str, phase: PhaseInfo) -> None:
        self.schedule(self._store.update_phase(
            job_id=job_id,
            step=phase.step,
            status=phase.status.value,
            finished_at=_utc(phase.finished_at),
            duration_seconds=phase.duration_seconds,
            output_summary=phase.output,
            files_changed=list(phase.files_changed),
        ))

    def update_job_terminal(
        self, job: JobInfo, *, session_id: str = "", error: str = "",
    ) -> None:
        self.schedule(self._store.update_job(
            job_id=job.job_id,
            status=job.status.value,
            finished_at=_utc(job.finished_at),
            duration_seconds=job.duration_seconds,
            session_id=session_id,
            error=error,
        ))
