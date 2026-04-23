"""Job Tracker — tracks long-running coding task progress in real-time.

Provides a central registry of active and recent jobs with phase-level
progress. Exposes state for web API, CLI, and messenger notifications.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger("breadmind.coding.tracker")


class JobStatus(str, Enum):
    PENDING = "pending"
    DECOMPOSING = "decomposing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PhaseInfo:
    step: int
    title: str
    status: PhaseStatus = PhaseStatus.PENDING
    started_at: float = 0
    finished_at: float = 0
    duration_seconds: float = 0
    output: str = ""
    files_changed: list[str] = field(default_factory=list)


@dataclass
class JobInfo:
    job_id: str
    project: str
    agent: str
    prompt: str
    status: JobStatus = JobStatus.PENDING
    phases: list[PhaseInfo] = field(default_factory=list)
    current_phase: int = 0
    total_phases: int = 0
    started_at: float = 0
    finished_at: float = 0
    duration_seconds: float = 0
    session_id: str = ""
    error: str = ""
    user: str = ""
    channel: str = ""

    @property
    def progress_pct(self) -> int:
        if self.total_phases == 0:
            return 0
        completed = sum(1 for p in self.phases if p.status == PhaseStatus.COMPLETED)
        return int((completed / self.total_phases) * 100)

    @property
    def completed_phases(self) -> int:
        return sum(1 for p in self.phases if p.status == PhaseStatus.COMPLETED)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "project": self.project,
            "agent": self.agent,
            "prompt": self.prompt[:200],
            "status": self.status.value,
            "current_phase": self.current_phase,
            "total_phases": self.total_phases,
            "completed_phases": self.completed_phases,
            "progress_pct": self.progress_pct,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "session_id": self.session_id,
            "error": self.error,
            "user": self.user,
            "channel": self.channel,
            "phases": [
                {
                    "step": p.step,
                    "title": p.title,
                    "status": p.status.value,
                    "duration_seconds": round(p.duration_seconds, 1),
                    "files_changed": p.files_changed,
                }
                for p in self.phases
            ],
        }


class JobTracker:
    """Central registry for tracking long-running coding jobs."""

    _instance: JobTracker | None = None

    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._listeners: list[Callable] = []  # async callbacks for real-time push
        self._max_history: int = 50
        self._store: Any | None = None  # JobStore | None — avoid hard import
        # DB write-through serializer: a single background worker drains
        # coroutines in FIFO order so concurrent UPDATEs to the same row
        # don't reorder via the asyncpg pool (max_size > 1).
        self._db_queue: asyncio.Queue | None = None
        self._db_worker: asyncio.Task | None = None
        # Log streaming (Task 6): WS-broadcast listeners + DB-batching buffer.
        # Log listeners fire immediately per append (raw ensure_future) for
        # low-latency WS push; DB writes are routed through LogBuffer which
        # batches by size/time and is force-flushed on complete_phase.
        self._log_listeners: list[Callable] = []
        self._log_buffer: Any | None = None  # LogBuffer | None
        self._line_counters: dict[tuple[str, int], int] = {}

    @classmethod
    def get_instance(cls) -> JobTracker:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def bind_store(self, store: Any) -> None:
        """Attach a :class:`JobStore` so state changes also write-through to DB.

        Writes are scheduled via ``asyncio.ensure_future`` and are
        best-effort: if no running event loop exists (e.g. offline unit
        tests), the write is silently skipped.
        """
        self._store = store

    # ── DB write-through helpers ─────────────────────────────────────────

    @staticmethod
    def _utc(ts: float) -> datetime | None:
        """Convert epoch seconds to a timezone-aware UTC datetime, or None."""
        if not ts:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def _db_schedule(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Fire-and-forget enqueue ``coro`` onto the DB write-through queue.

        A single background worker (lazily created on first call) drains
        the queue in FIFO order so writes stay serialized even when the
        underlying asyncpg pool has multiple connections. Swallows
        ``RuntimeError`` raised when no loop is running (common in
        offline unit-test paths) by closing ``coro`` to avoid the
        "coroutine was never awaited" warning.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        if self._db_queue is None:
            self._db_queue = asyncio.Queue()
        if self._db_worker is None or self._db_worker.done():
            self._db_worker = loop.create_task(self._db_worker_loop())
        self._db_queue.put_nowait(coro)

    async def _db_worker_loop(self) -> None:
        """Drain ``self._db_queue`` one coroutine at a time."""
        assert self._db_queue is not None
        while True:
            coro = await self._db_queue.get()
            try:
                await coro
            except Exception as exc:
                logger.warning("JobTracker DB write-through failed: %s", exc)
            finally:
                self._db_queue.task_done()

    def _db_insert_job(self, job: JobInfo) -> None:
        if self._store is None:
            return
        started_at = self._utc(job.started_at) or datetime.now(timezone.utc)
        self._db_schedule(self._store.insert_job(
            job_id=job.job_id,
            project=job.project,
            agent=job.agent,
            prompt=job.prompt,
            user_name=job.user,
            channel=job.channel,
            started_at=started_at,
            status=job.status.value,
        ))

    def _db_update_job_status(self, job: JobInfo) -> None:
        if self._store is None:
            return
        self._db_schedule(self._store.update_job(
            job_id=job.job_id,
            status=job.status.value,
        ))

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
        self._db_insert_job(job)
        logger.info("Job created: %s (%s)", job_id, project)
        return job

    def set_decomposing(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.DECOMPOSING
            self._emit("job_decomposing", job)
            self._db_update_job_status(job)

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
        if self._store is not None:
            phase_payload = [
                {"step": p.step, "title": p.title} for p in job.phases
            ]
            self._db_schedule(self._store.insert_phases(job_id, phase_payload))
            self._db_schedule(self._store.update_job(
                job_id=job_id,
                status=job.status.value,
                total_phases=job.total_phases,
            ))

    def start_phase(self, job_id: str, step: int) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.current_phase = step
        started_at: float = 0.0
        for p in job.phases:
            if p.step == step:
                p.status = PhaseStatus.RUNNING
                p.started_at = time.time()
                started_at = p.started_at
                break
        # Reset per-phase line counter — append_log increments before use.
        self._line_counters[(job_id, step)] = 0
        self._emit("phase_started", job)
        if self._store is not None:
            self._db_schedule(self._store.update_phase(
                job_id=job_id,
                step=step,
                status=PhaseStatus.RUNNING.value,
                started_at=self._utc(started_at),
            ))

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
        if self._store is not None and updated is not None:
            self._db_schedule(self._store.update_phase(
                job_id=job_id,
                step=updated.step,
                status=updated.status.value,
                finished_at=self._utc(updated.finished_at),
                duration_seconds=updated.duration_seconds,
                output_summary=updated.output,
                files_changed=list(updated.files_changed),
            ))
        # Force-flush any buffered logs for this phase so the UI's "final"
        # view after phase completion doesn't miss the last partial batch.
        # Raw ensure_future per spec: LogBuffer serializes via its own lock
        # and insert_log_batch is append-only, so this does not need to go
        # through the _db_queue path.
        if self._log_buffer is not None:
            try:
                asyncio.ensure_future(self._log_buffer.force_flush(job_id, step))
            except RuntimeError:
                pass

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
        if self._store is not None:
            self._db_schedule(self._store.update_job(
                job_id=job_id,
                status=job.status.value,
                finished_at=self._utc(job.finished_at),
                duration_seconds=job.duration_seconds,
                session_id=session_id,
                error=error,
            ))
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
        if self._store is not None:
            self._db_schedule(self._store.update_job(
                job_id=job_id,
                status=job.status.value,
                finished_at=self._utc(job.finished_at),
                duration_seconds=job.duration_seconds,
            ))
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

    # ── Log streaming (Task 6) ───────────────────────────────────────────

    def bind_log_buffer(self, buffer: Any) -> None:
        """Attach a :class:`LogBuffer` that batches DB writes for log lines.

        The buffer is expected to expose ``append(job_id, step, line_no, text)``
        and ``force_flush(job_id, step)`` coroutines. Typically constructed
        with ``flush_fn=JobTracker.make_default_flush(store)``.
        """
        self._log_buffer = buffer

    def add_log_listener(self, callback: Callable) -> None:
        """Register a WS-broadcast callback fired on every ``append_log``.

        Callback signature: ``async (job_id, step, line_no, ts, text) -> None``.
        Listeners are invoked fire-and-forget via ``ensure_future`` so a slow
        consumer cannot throttle log ingestion.
        """
        self._log_listeners.append(callback)

    def remove_log_listener(self, callback: Callable) -> None:
        self._log_listeners = [
            cb for cb in self._log_listeners if cb is not callback
        ]

    async def append_log(
        self, job_id: str, step: int, text: str,
    ) -> None:
        """Record a log line for ``(job_id, step)``.

        Assigns a monotonically increasing ``line_no`` starting from 1 per
        phase (reset in ``start_phase``). Fires listeners immediately for
        low-latency WS push, then delegates DB persistence to the bound
        :class:`LogBuffer`.

        The buffered DB flush bypasses Task 5's ``_db_queue`` serializer
        (it's append-only and ordering-safe on its own), but log rows FK
        into ``coding_jobs`` / ``coding_phases`` — so we first drain any
        pending setup writes (``insert_job`` / ``insert_phases``) to
        guarantee the parent rows exist before the batch INSERT fires.
        """
        key = (job_id, step)
        self._line_counters[key] = self._line_counters.get(key, 0) + 1
        line_no = self._line_counters[key]
        ts = datetime.now(timezone.utc)
        # Fire listeners immediately — raw ensure_future, fire-and-forget.
        for cb in list(self._log_listeners):
            try:
                asyncio.ensure_future(cb(job_id, step, line_no, ts, text))
            except RuntimeError:
                # No event loop (offline unit-test path) — skip
                pass
        # Buffered DB write — LogBuffer aggregates and flushes in batches.
        if self._log_buffer is not None:
            # Drain the DB write-through queue so the job/phase rows this
            # log FKs into are durable before a size-triggered flush fires.
            # Cheap (returns immediately) once the queue is idle.
            if self._db_queue is not None:
                await self._db_queue.join()
            await self._log_buffer.append(job_id, step, line_no, text)

    @staticmethod
    def make_default_flush(store: Any) -> Callable:
        """Return a :class:`LogBuffer` ``flush_fn`` that writes to ``store``.

        Batches arrive as a flat list of ``(job_id, step, line_no, ts, text)``
        tuples; we regroup by ``job_id`` so each :meth:`JobStore.insert_log_batch`
        call honours its per-job API shape.
        """
        async def flush(
            batch: list[tuple[str, int, int, datetime, str]],
        ) -> None:
            by_job: dict[str, list[tuple[int, int, datetime, str]]] = {}
            for job_id, step, line_no, ts, text in batch:
                by_job.setdefault(job_id, []).append((step, line_no, ts, text))
            for job_id, items in by_job.items():
                await store.insert_log_batch(job_id, items)

        return flush

    # ── Cleanup ──────────────────────────────────────────────────────────

    def _cleanup_history(self) -> None:
        """Remove old completed jobs beyond max_history."""
        completed = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        if len(completed) > self._max_history:
            completed.sort(key=lambda j: j.finished_at)
            for j in completed[: len(completed) - self._max_history]:
                self._jobs.pop(j.job_id, None)
