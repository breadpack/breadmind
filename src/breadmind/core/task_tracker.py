"""In-session structured task tracking with dependency graphs."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TrackedTask:
    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    owner: str = ""  # agent_id
    blocks: list[str] = field(default_factory=list)  # task IDs this blocks
    blocked_by: list[str] = field(default_factory=list)  # task IDs blocking this
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TaskTracker:
    """In-session task tracking with file persistence."""

    def __init__(self, persist_dir: str | None = None) -> None:
        self._tasks: dict[str, TrackedTask] = {}
        self._persist_dir = persist_dir
        if persist_dir:
            os.makedirs(persist_dir, exist_ok=True)
            self._load()

    def create(self, title: str, description: str = "",
               blocked_by: list[str] | None = None,
               owner: str = "", metadata: dict | None = None) -> TrackedTask:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        task = TrackedTask(
            id=task_id, title=title, description=description,
            blocked_by=blocked_by or [], owner=owner,
            metadata=metadata or {},
        )
        # Update reverse dependencies
        for dep_id in task.blocked_by:
            dep = self._tasks.get(dep_id)
            if dep and task_id not in dep.blocks:
                dep.blocks.append(task_id)
        self._tasks[task_id] = task
        self._persist()
        return task

    def update(self, task_id: str, status: TaskStatus | None = None,
               title: str | None = None, owner: str | None = None,
               metadata: dict | None = None) -> TrackedTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        if status:
            task.status = status
        if title:
            task.title = title
        if owner is not None:
            task.owner = owner
        if metadata:
            task.metadata.update(metadata)
        task.updated_at = time.time()
        self._persist()
        return task

    def get(self, task_id: str) -> TrackedTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None,
                   owner: str | None = None) -> list[TrackedTask]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        if owner:
            tasks = [t for t in tasks if t.owner == owner]
        return sorted(tasks, key=lambda t: t.created_at)

    def delete(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            # Clean up references
            for t in self._tasks.values():
                if task_id in t.blocks:
                    t.blocks.remove(task_id)
                if task_id in t.blocked_by:
                    t.blocked_by.remove(task_id)
            self._persist()
            return True
        return False

    def get_ready_tasks(self) -> list[TrackedTask]:
        """Get tasks that are pending and have all dependencies completed."""
        return [
            t for t in self._tasks.values()
            if t.status == TaskStatus.PENDING
            and all(
                self._tasks.get(dep, TrackedTask(id="", title="")).status == TaskStatus.COMPLETED
                for dep in t.blocked_by
            )
        ]

    def _persist(self) -> None:
        if not self._persist_dir:
            return
        data = {tid: self._task_to_dict(t) for tid, t in self._tasks.items()}
        path = os.path.join(self._persist_dir, "tasks.json")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        path = os.path.join(self._persist_dir, "tasks.json")
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for tid, td in data.items():
                self._tasks[tid] = TrackedTask(
                    id=tid, title=td["title"],
                    description=td.get("description", ""),
                    status=TaskStatus(td.get("status", "pending")),
                    owner=td.get("owner", ""),
                    blocks=td.get("blocks", []),
                    blocked_by=td.get("blocked_by", []),
                    metadata=td.get("metadata", {}),
                    created_at=td.get("created_at", 0),
                    updated_at=td.get("updated_at", 0),
                )
        except (json.JSONDecodeError, KeyError):
            pass

    @staticmethod
    def _task_to_dict(t: TrackedTask) -> dict:
        return {
            "title": t.title, "description": t.description,
            "status": t.status.value, "owner": t.owner,
            "blocks": t.blocks, "blocked_by": t.blocked_by,
            "metadata": t.metadata, "created_at": t.created_at,
            "updated_at": t.updated_at,
        }
