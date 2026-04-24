"""Data classes for the coding-job tracker subsystem.

Extracted from job_tracker.py (spec 2026-04-24). Kept import-only so that
JobDbWriter / JobLogStream can depend on these types without circular imports
back into JobTracker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
