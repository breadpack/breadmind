"""Per-project hourly page budget for connector ingestion.

Connectors paginate potentially unbounded external sources (Confluence, Jira,
Drive). To keep a single runaway project from monopolising worker capacity or
burning through a provider's rate limit, each project gets an independent
sliding hourly window capped at ``limit`` pages.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

__all__ = ["BudgetExceeded", "HourlyPageBudget"]


class BudgetExceeded(Exception):
    """Raised when a project would exceed its hourly page budget."""


@dataclass
class _Window:
    start: float = 0.0
    count: int = 0


@dataclass
class HourlyPageBudget:
    """Sliding-hour page budget keyed by ``(project_id, instance_id)``.

    Keys are ``(project_id, instance_id)`` so a single project can run
    independent budgets per source instance (e.g., two Slack workspaces).
    Callers that don't need the second dimension simply omit ``instance_id``;
    the default ``None`` makes ``(project_id, None)`` the legacy key.

    The window is reset lazily when ``now() - window.start >= 3600`` on the
    next :meth:`consume` call for that key — there is no background timer.

    .. warning::
       **Single-process only.** State lives in a process-local ``dict``; it
       is *not* shared across Celery worker processes, across gunicorn/uvicorn
       workers, or across hosts. When deploying with multiple worker
       processes each worker enforces an independent budget, so a project's
       effective cap is ``limit * num_workers`` per hour.

       For multi-worker deployments where strict global budget enforcement
       matters, swap in a Redis-backed backend (out of scope for P5 —
       tracked as a follow-up).
    """

    limit: int = 1000
    now: Callable[[], float] = field(default_factory=lambda: time.monotonic)
    _windows: dict[tuple[uuid.UUID, str | None], _Window] = field(default_factory=dict)

    async def consume(
        self,
        project_id: uuid.UUID,
        count: int = 1,
        *,
        instance_id: str | None = None,
    ) -> None:
        t = self.now()
        key = (project_id, instance_id)
        window = self._windows.get(key)
        if window is None or t - window.start >= 3600.0:
            window = _Window(start=t, count=0)
            self._windows[key] = window
        if window.count + count > self.limit:
            raise BudgetExceeded(
                f"project {project_id} (instance={instance_id}) exceeded hourly "
                f"page budget ({window.count}+{count} > {self.limit})"
            )
        window.count += count

    def reset(self, project_id: uuid.UUID, instance_id: str | None = None) -> None:
        self._windows.pop((project_id, instance_id), None)
