"""Job Tracker — tracks long-running coding task progress in real-time.

Provides a central registry of active and recent jobs with phase-level
progress. Exposes state for web API, CLI, and messenger notifications.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from breadmind.metrics import (
    coding_active_jobs,
    coding_job_duration_seconds,
    coding_jobs_total,
)
from breadmind.coding.job_db_writer import JobDbWriter
from breadmind.coding.job_log_stream import JobLogStream
from breadmind.coding.job_models import (
    JobInfo,
    JobStatus,
    PhaseInfo,
    PhaseStatus,
)

# Re-export for backwards compatibility — existing call sites import
# `from breadmind.coding.job_tracker import JobInfo` etc.
__all__ = ["JobTracker", "JobInfo", "JobStatus", "PhaseInfo", "PhaseStatus"]

logger = logging.getLogger("breadmind.coding.tracker")


class JobTracker:
    """Central registry for tracking long-running coding jobs."""

    _instance: JobTracker | None = None

    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._listeners: list[Callable] = []  # async callbacks for real-time push
        self._max_history: int = 50
        self._store: Any | None = None  # JobStore | None — avoid hard import
        self._db_writer: JobDbWriter | None = None  # bound in bind_store
        self._log_stream: JobLogStream | None = None  # bound by bind_log_buffer OR bind_store

    @classmethod
    def get_instance(cls) -> JobTracker:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def bind_store(self, store: Any) -> None:
        """Attach a :class:`JobStore` so state changes also write-through to DB.

        Writes are serialized via :class:`JobDbWriter`'s single FIFO queue so
        concurrent UPDATEs to the same row don't reorder across the asyncpg
        pool (max_size > 1). Best-effort: no running loop = silent skip.
        """
        self._store = store
        self._db_writer = JobDbWriter(store)
        if self._log_stream is None:
            self._log_stream = JobLogStream(db_writer=self._db_writer)
        else:
            self._log_stream._db_writer = self._db_writer

    # ── Job lifecycle ────────────────────────────────────────────────────

    def create_job(
        self,
        job_id: str,
        project: str,
        agent: str,
        prompt: str,
        user: str = "",
        channel: str = "",
    ) -> JobInfo:
        job = JobInfo(
            job_id=job_id,
            project=project,
            agent=agent,
            prompt=prompt,
            status=JobStatus.PENDING,
            started_at=time.time(),
            user=user,
            channel=channel,
        )
        self._jobs[job_id] = job
        self._emit("job_created", job)
        if self._db_writer is not None:
            self._db_writer.insert_job(job)
        coding_active_jobs.set(len(self.get_active_jobs()))
        logger.info("Job created: %s (%s)", job_id, project)
        return job

    def set_decomposing(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.DECOMPOSING
            self._emit("job_decomposing", job)
            if self._db_writer is not None:
                self._db_writer.update_job_status(job)

    def set_phases(self, job_id: str, phases: list[dict]) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.total_phases = len(phases)
        job.phases = [
            PhaseInfo(step=p.get("step", i + 1), title=p.get("title", f"Phase {i + 1}"))
            for i, p in enumerate(phases)
        ]
        job.status = JobStatus.RUNNING
        self._emit("job_running", job)
        # DB write-through: insert phase rows + patch job.total_phases/status.
        if self._db_writer is not None:
            self._db_writer.insert_phases(job_id, job.phases)
            self._db_writer.update_job_total_phases(job)

    def start_phase(self, job_id: str, step: int) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.current_phase = step
        target: PhaseInfo | None = None
        for p in job.phases:
            if p.step == step:
                p.status = PhaseStatus.RUNNING
                p.started_at = time.time()
                target = p
                break
        # Reset per-phase line counter — append_log increments before use.
        if self._log_stream is not None:
            self._log_stream.reset_phase_counter(job_id, step)
        self._emit("phase_started", job)
        if self._db_writer is not None and target is not None:
            self._db_writer.update_phase_started(job_id, target)

    def complete_phase(
        self,
        job_id: str,
        step: int,
        success: bool,
        output: str = "",
        files_changed: list[str] | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        updated: PhaseInfo | None = None
        for p in job.phases:
            if p.step == step:
                p.status = PhaseStatus.COMPLETED if success else PhaseStatus.FAILED
                p.finished_at = time.time()
                p.duration_seconds = p.finished_at - p.started_at if p.started_at else 0
                p.output = output[:500]
                p.files_changed = files_changed or []
                updated = p
                break
        self._emit("phase_completed", job)
        if self._db_writer is not None and updated is not None:
            self._db_writer.update_phase_finished(job_id, updated)
        # Force-flush any buffered logs for this phase so the UI's "final"
        # view after phase completion doesn't miss the last partial batch.
        if self._log_stream is not None:
            self._log_stream.force_flush_phase(job_id, step)

    def complete_job(
        self,
        job_id: str,
        success: bool,
        session_id: str = "",
        error: str = "",
    ) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = JobStatus.COMPLETED if success else JobStatus.FAILED
        job.finished_at = time.time()
        job.duration_seconds = job.finished_at - job.started_at
        job.session_id = session_id
        job.error = error
        self._emit("job_completed", job)
        if self._db_writer is not None:
            self._db_writer.update_job_terminal(job, session_id=session_id, error=error)
        # Prometheus: terminal counter + duration histogram, then refresh
        # the gauge using the live active-jobs set (handles concurrent
        # completions and duplicate calls idempotently).
        coding_jobs_total.labels(status=job.status.value).inc()
        coding_job_duration_seconds.observe(job.duration_seconds)
        coding_active_jobs.set(len(self.get_active_jobs()))
        logger.info(
            "Job %s: %s (%.1fs, %d/%d phases)",
            "completed" if success else "failed",
            job_id, job.duration_seconds,
            job.completed_phases, job.total_phases,
        )
        self._cleanup_history()

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return False
        job.status = JobStatus.CANCELLED
        job.finished_at = time.time()
        job.duration_seconds = job.finished_at - job.started_at
        self._emit("job_cancelled", job)
        if self._db_writer is not None:
            self._db_writer.update_job_terminal(job)
        coding_jobs_total.labels(status=job.status.value).inc()
        coding_active_jobs.set(len(self.get_active_jobs()))
        return True

    # ── Queries ──────────────────────────────────────────────────────────

    def get_job(self, job_id: str) -> JobInfo | None:
        return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[JobInfo]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status.value == status]
        return sorted(jobs, key=lambda j: j.started_at, reverse=True)

    def get_active_jobs(self) -> list[JobInfo]:
        return [
            j for j in self._jobs.values()
            if j.status in (JobStatus.PENDING, JobStatus.DECOMPOSING, JobStatus.RUNNING)
        ]

    # ── Event listeners ──────────────────────────────────────────────────

    def add_listener(self, callback: Callable) -> None:
        """Add an async callback: callback(event_type: str, job: JobInfo)."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable) -> None:
        self._listeners = [cb for cb in self._listeners if cb is not callback]

    def _emit(self, event_type: str, job: JobInfo) -> None:
        for cb in self._listeners:
            try:
                asyncio.ensure_future(cb(event_type, job))
            except RuntimeError:
                # No event loop — skip
                pass

    # ── Log streaming ────────────────────────────────────────────────────

    def bind_log_buffer(self, buffer: Any) -> None:
        """Attach a :class:`LogBuffer` and auto-start its worker.

        Called from sync context, so we use ``create_task(buffer.start())``
        fire-and-forget. ``start()`` only schedules the background loop, so
        no await is needed; if there's no running loop (offline test path),
        the start is silently skipped — caller can invoke ``buffer.start()``
        explicitly later.
        """
        if self._log_stream is None:
            self._log_stream = JobLogStream(db_writer=self._db_writer)
        self._log_stream.bind_buffer(buffer)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(buffer.start())

    def add_log_listener(self, callback: Callable) -> None:
        """Register a WS-broadcast callback fired on every ``append_log``.

        Callback signature: ``async (job_id, step, line_no, ts, text) -> None``.
        Listeners are invoked fire-and-forget via ``ensure_future`` so a slow
        consumer cannot throttle log ingestion.
        """
        if self._log_stream is None:
            self._log_stream = JobLogStream(db_writer=self._db_writer)
        self._log_stream.add_listener(callback)

    def remove_log_listener(self, callback: Callable) -> None:
        if self._log_stream is not None:
            self._log_stream.remove_listener(callback)

    async def append_log(
        self, job_id: str, step: int, text: str,
    ) -> None:
        """Record a log line for ``(job_id, step)``.

        Delegates to :class:`JobLogStream` which assigns monotonically
        increasing line numbers, fires listeners, and buffers DB writes.
        """
        if self._log_stream is None:
            return
        await self._log_stream.append(job_id, step, text)

    @staticmethod
    def make_default_flush(store: Any) -> Callable:
        """Return a :class:`LogBuffer` ``flush_fn`` that writes to ``store``.

        Thin delegator to :meth:`JobLogStream.make_default_flush` — kept here
        for backward compatibility (existing callers use
        ``JobTracker.make_default_flush(store)``).
        """
        return JobLogStream.make_default_flush(store)

    # ── Cleanup ──────────────────────────────────────────────────────────

    def _cleanup_history(self) -> None:
        """Remove old completed jobs beyond max_history.

        Also evicts the JobLogStream line counters for any popped job so
        long-running operation doesn't accumulate counter entries.
        """
        completed = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        if len(completed) > self._max_history:
            completed.sort(key=lambda j: j.finished_at)
            for j in completed[: len(completed) - self._max_history]:
                self._jobs.pop(j.job_id, None)
                if self._log_stream is not None:
                    self._log_stream.evict_job_counters(j.job_id)
