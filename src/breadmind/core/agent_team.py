"""Agent team orchestration: multiple agents collaborating on shared task lists."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # waiting on dependency


@dataclass
class TeamTask:
    """A task in the shared task list."""
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None  # agent_id
    depends_on: list[str] = field(default_factory=list)  # task IDs
    result: str = ""
    created_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None


@dataclass
class TeamMessage:
    """Inter-agent message."""
    id: str
    from_agent: str
    to_agent: str  # "*" for broadcast
    content: str
    timestamp: float = field(default_factory=time.monotonic)
    reply_to: str | None = None


@dataclass
class TeammateConfig:
    """Configuration for a team member."""
    agent_id: str
    name: str
    role: str  # e.g. "implementer", "reviewer", "tester"
    tools: list[str] = field(default_factory=list)  # allowed tool names
    model: str = ""  # optional model override
    system_prompt: str = ""


class TaskBoard:
    """Shared task board for the team."""

    def __init__(self) -> None:
        self._tasks: dict[str, TeamTask] = {}
        self._lock = asyncio.Lock()

    async def add_task(self, title: str, description: str = "",
                       depends_on: list[str] | None = None) -> TeamTask:
        async with self._lock:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = TeamTask(
                id=task_id, title=title, description=description,
                depends_on=depends_on or [],
            )
            self._tasks[task_id] = task
            return task

    async def claim_task(self, agent_id: str) -> TeamTask | None:
        """Claim the next available task (auto-coordination)."""
        async with self._lock:
            for task in self._tasks.values():
                if task.status != TaskStatus.PENDING:
                    continue
                # Check dependencies are all completed
                if all(self._tasks[dep].status == TaskStatus.COMPLETED
                       for dep in task.depends_on if dep in self._tasks):
                    task.status = TaskStatus.IN_PROGRESS
                    task.assigned_to = agent_id
                    return task
            return None

    async def complete_task(self, task_id: str, result: str = "") -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = time.monotonic()
                # Auto-unblock dependent tasks
                self._check_unblock()

    async def fail_task(self, task_id: str, error: str = "") -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.result = f"FAILED: {error}"

    def _check_unblock(self) -> None:
        """Check if any blocked tasks can be unblocked."""
        for task in self._tasks.values():
            if task.status == TaskStatus.BLOCKED:
                if all(self._tasks[dep].status == TaskStatus.COMPLETED
                       for dep in task.depends_on if dep in self._tasks):
                    task.status = TaskStatus.PENDING

    def get_all_tasks(self) -> list[TeamTask]:
        return list(self._tasks.values())

    def get_pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)

    def get_progress(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for task in self._tasks.values():
            counts[task.status.value] += 1
        return dict(counts)

    @property
    def all_done(self) -> bool:
        return all(t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                   for t in self._tasks.values())


class Mailbox:
    """Inter-agent messaging system."""

    def __init__(self) -> None:
        self._messages: dict[str, list[TeamMessage]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def send(self, from_agent: str, to_agent: str, content: str,
                   reply_to: str | None = None) -> TeamMessage:
        msg = TeamMessage(
            id=f"msg_{uuid.uuid4().hex[:8]}",
            from_agent=from_agent, to_agent=to_agent,
            content=content, reply_to=reply_to,
        )
        async with self._lock:
            if to_agent == "*":
                # Broadcast - add to all known mailboxes
                for box in self._messages.values():
                    box.append(msg)
            else:
                self._messages[to_agent].append(msg)
        return msg

    async def receive(self, agent_id: str, limit: int = 10) -> list[TeamMessage]:
        """Get and clear messages for an agent."""
        async with self._lock:
            messages = self._messages.get(agent_id, [])[:limit]
            if agent_id in self._messages:
                self._messages[agent_id] = self._messages[agent_id][limit:]
            return messages


class AgentTeam:
    """Orchestrates a team of agents working on shared tasks."""

    def __init__(self, name: str, lead_id: str = "") -> None:
        self._name = name
        self._lead_id = lead_id or f"lead_{uuid.uuid4().hex[:8]}"
        self._teammates: dict[str, TeammateConfig] = {}
        self._task_board = TaskBoard()
        self._mailbox = Mailbox()
        self._running = False
        self._agent_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def task_board(self) -> TaskBoard:
        return self._task_board

    @property
    def mailbox(self) -> Mailbox:
        return self._mailbox

    def add_teammate(self, config: TeammateConfig) -> None:
        self._teammates[config.agent_id] = config

    def remove_teammate(self, agent_id: str) -> bool:
        return self._teammates.pop(agent_id, None) is not None

    async def start(self, task_handler: Callable[[str, TeamTask, Mailbox], Awaitable[str]]) -> None:
        """Start the team. Each teammate runs a loop claiming and executing tasks.

        task_handler(agent_id, task, mailbox) -> result string
        """
        self._running = True
        for agent_id in self._teammates:
            self._agent_tasks[agent_id] = asyncio.create_task(
                self._agent_loop(agent_id, task_handler)
            )

    async def wait_until_done(self, timeout: float = 300) -> dict[str, Any]:
        """Wait for all tasks to complete or timeout."""
        start = time.monotonic()
        while not self._task_board.all_done:
            if time.monotonic() - start > timeout:
                break
            await asyncio.sleep(0.5)

        self._running = False
        # Cancel remaining agent loops
        for task in self._agent_tasks.values():
            if not task.done():
                task.cancel()

        return {
            "team": self._name,
            "progress": self._task_board.get_progress(),
            "tasks": [
                {"id": t.id, "title": t.title, "status": t.status.value,
                 "assigned_to": t.assigned_to, "result": t.result[:200]}
                for t in self._task_board.get_all_tasks()
            ],
        }

    async def _agent_loop(self, agent_id: str,
                          task_handler: Callable[..., Awaitable[str]]) -> None:
        """Main loop for a single agent: claim task -> execute -> repeat."""
        while self._running and not self._task_board.all_done:
            # Check messages first
            messages = await self._mailbox.receive(agent_id)

            # Try to claim a task
            task = await self._task_board.claim_task(agent_id)
            if task is None:
                await asyncio.sleep(0.5)
                continue

            try:
                result = await task_handler(agent_id, task, self._mailbox)
                await self._task_board.complete_task(task.id, result)
            except Exception as e:
                logger.error("Agent %s failed task %s: %s", agent_id, task.id, e)
                await self._task_board.fail_task(task.id, str(e))

    def get_status(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "lead": self._lead_id,
            "teammates": list(self._teammates.keys()),
            "running": self._running,
            "progress": self._task_board.get_progress(),
        }
