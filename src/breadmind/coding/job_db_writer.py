"""DB write-through serializer for JobTracker (extracted from job_tracker.py).

Per-loop FIFO queue + per-loop worker preserves the ordering guarantee that
prevents `status='running'` from committing after `status='completed'`
under asyncpg pool max_size > 1. Each event loop (pytest, uvicorn, etc.) gets
its own (queue, task) pair keyed by id(loop). The task's done_callback pops
the dict entry when the task finishes. Production teardown (asyncio.Runner.close(),
uvicorn shutdown) cancels tasks as part of its normal sequence, which fires
the done_callback.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Coroutine

from breadmind.coding.job_models import JobInfo, PhaseInfo, PhaseStatus
from breadmind.metrics import coding_db_writer_drops_total

logger = logging.getLogger(__name__)


def _utc(ts: float) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


@dataclass
class _LoopWorker:
    queue: asyncio.Queue
    task: asyncio.Task


class JobDbWriter:
    """Best-effort DB write-through for JobTracker state mutations."""

    def __init__(
        self,
        store: Any,
        *,
        max_queue_size: int | None = None,
    ) -> None:
        self._store = store
        if max_queue_size is None:
            raw = int(os.getenv("BREADMIND_CODING_DB_QUEUE_MAX", "2000"))
            if raw <= 0:
                logger.warning(
                    "BREADMIND_CODING_DB_QUEUE_MAX=%d is ambiguous (asyncio "
                    "treats 0/negative as unbounded); using default 2000.",
                    raw,
                )
                raw = 2000
            self._max_queue_size = raw
        else:
            self._max_queue_size = max_queue_size
        self._workers: dict[int, _LoopWorker] = {}

    # ── Scheduling ──────────────────────────────────────────────────────

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coding_db_writer_drops_total.labels(reason="no_loop").inc()
            coro.close()
            return
        worker = self._workers.get(id(loop))
        if worker is None:
            worker = self._spawn(loop)
        if worker.queue.full():
            coding_db_writer_drops_total.labels(reason="queue_full").inc()
            coro.close()
            return
        worker.queue.put_nowait(coro)

    def _spawn(self, loop: asyncio.AbstractEventLoop) -> _LoopWorker:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        task = loop.create_task(self._worker_loop(q))
        loop_id = id(loop)
        worker = _LoopWorker(queue=q, task=task)
        self._workers[loop_id] = worker
        task.add_done_callback(lambda _t: self._workers.pop(loop_id, None))
        return worker

    async def _worker_loop(self, q: asyncio.Queue) -> None:
        while True:
            coro = await q.get()
            try:
                await coro
            except asyncio.CancelledError:
                # Worker is being torn down — close the in-flight coro
                # and exit the loop. done_callback will pop the entry.
                if hasattr(coro, "close"):
                    coro.close()
                raise
            except Exception as exc:
                logger.warning("JobDbWriter coro failed: %s", exc)
                coding_db_writer_drops_total.labels(reason="coro_failed").inc()
            finally:
                q.task_done()

    async def join(self) -> None:
        """Wait until the *current loop's* queue drains."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        worker = self._workers.get(id(loop))
        if worker is not None:
            await worker.queue.join()

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
