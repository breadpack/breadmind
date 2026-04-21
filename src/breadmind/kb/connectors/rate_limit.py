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
    """Sliding-hour page budget keyed by project id.

    The window is reset lazily when ``now() - window.start >= 3600`` on the
    next :meth:`consume` call for that project — there is no background timer.
    """

    limit: int = 1000
    now: Callable[[], float] = field(default_factory=lambda: time.monotonic)
    _windows: dict[uuid.UUID, _Window] = field(default_factory=dict)

    async def consume(self, project_id: uuid.UUID, count: int = 1) -> None:
        t = self.now()
        window = self._windows.get(project_id)
        if window is None or t - window.start >= 3600.0:
            window = _Window(start=t, count=0)
            self._windows[project_id] = window
        if window.count + count > self.limit:
            raise BudgetExceeded(
                f"project {project_id} exceeded hourly page budget "
                f"({window.count}+{count} > {self.limit})"
            )
        window.count += count

    def reset(self, project_id: uuid.UUID) -> None:
        self._windows.pop(project_id, None)
