"""Job Tracker — tracks long-running coding task progress in real-time.

Provides a central registry of active and recent jobs with phase-level
progress. Exposes state for web API, CLI, and messenger notifications.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

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

    @classmethod
    def get_instance(cls) -> JobTracker:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

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
        logger.info("Job created: %s (%s)", job_id, project)
        return job

    def set_decomposing(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = JobStatus.DECOMPOSING
            self._emit("job_decomposing", job)

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

    def start_phase(self, job_id: str, step: int) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.current_phase = step
        for p in job.phases:
            if p.step == step:
                p.status = PhaseStatus.RUNNING
                p.started_at = time.time()
                break
        self._emit("phase_started", job)

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
        for p in job.phases:
            if p.step == step:
                p.status = PhaseStatus.COMPLETED if success else PhaseStatus.FAILED
                p.finished_at = time.time()
                p.duration_seconds = p.finished_at - p.started_at if p.started_at else 0
                p.output = output[:500]
                p.files_changed = files_changed or []
                break
        self._emit("phase_completed", job)

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
