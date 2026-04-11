"""Cloud Scheduled Tasks — schedule tasks for remote/cloud execution.

Tasks can be one-shot or recurring (cron).  They execute on a configured
remote endpoint (worker node or cloud service).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import partial

from breadmind.utils.helpers import generate_short_id


class CloudTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_CRON_RE = re.compile(
    r"^(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)$"
)


@dataclass
class CloudTask:
    id: str = field(default_factory=partial(generate_short_id, 12))
    prompt: str = ""
    schedule: str = ""  # cron expression or "once"
    status: CloudTaskStatus = CloudTaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_run: datetime | None = None
    result: str | None = None
    error: str | None = None
    endpoint: str = ""  # Remote execution endpoint


class CloudScheduler:
    """Schedule tasks for remote/cloud execution.

    Tasks can be one-shot or recurring (cron). They execute
    on a configured remote endpoint (worker node or cloud service).
    """

    def __init__(self, endpoint: str = "", api_key: str = "") -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._tasks: dict[str, CloudTask] = {}

    async def schedule(self, prompt: str, schedule: str = "once") -> CloudTask:
        """Schedule a new cloud task."""
        if not self._validate_schedule(schedule):
            raise ValueError(f"Invalid schedule expression: {schedule!r}")

        task = CloudTask(
            prompt=prompt,
            schedule=schedule,
            endpoint=self._endpoint,
        )
        self._tasks[task.id] = task
        return task

    async def cancel(self, task_id: str) -> bool:
        """Cancel a scheduled task.  Returns True if it was found and cancelled."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status in (CloudTaskStatus.COMPLETED, CloudTaskStatus.CANCELLED):
            return False
        task.status = CloudTaskStatus.CANCELLED
        return True

    async def get_status(self, task_id: str) -> CloudTask | None:
        return self._tasks.get(task_id)

    async def list_tasks(
        self, status: CloudTaskStatus | None = None
    ) -> list[CloudTask]:
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    async def execute_remote(self, task: CloudTask) -> str:
        """Execute task on remote endpoint.  Returns result.

        In production this would make an HTTP request to the worker endpoint.
        Here we simulate the execution lifecycle.
        """
        task.status = CloudTaskStatus.RUNNING
        task.last_run = datetime.now(timezone.utc)

        try:
            # Simulated execution — in real implementation this would POST to
            # task.endpoint with task.prompt and self._api_key
            result = f"executed:{task.prompt}"
            task.result = result
            task.status = CloudTaskStatus.COMPLETED
            return result
        except Exception as exc:  # pragma: no cover
            task.error = str(exc)
            task.status = CloudTaskStatus.FAILED
            raise

    def _validate_schedule(self, schedule: str) -> bool:
        if schedule == "once":
            return True
        return _CRON_RE.match(schedule.strip()) is not None
