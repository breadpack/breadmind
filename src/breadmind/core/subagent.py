import asyncio
import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SubAgentTask:
    id: str
    parent_id: str | None  # parent agent session
    task: str  # message/instruction
    status: str = "pending"  # pending, running, completed, failed
    result: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    model: str | None = None
    container_isolated: bool = False


class SubAgentManager:
    """Manage sub-agent spawning for task delegation."""

    def __init__(self, agent_factory=None):
        """agent_factory: callable that creates a new agent instance for isolated execution."""
        self._agent_factory = agent_factory
        self._tasks: dict[str, SubAgentTask] = {}
        self._lock = asyncio.Lock()
        self._message_handler = None  # Set externally

    def set_message_handler(self, handler):
        """Set the message handler for sub-agent execution."""
        self._message_handler = handler

    async def spawn(self, task: str, parent_id: str = None, model: str = None,
                    container_isolated: bool = False) -> SubAgentTask:
        """Spawn a new sub-agent to handle a task asynchronously."""
        task_id = str(uuid.uuid4())[:8]
        sa_task = SubAgentTask(
            id=task_id, parent_id=parent_id, task=task,
            status="pending", model=model,
            container_isolated=container_isolated,
        )
        async with self._lock:
            self._tasks[task_id] = sa_task

        # Execute in background
        asyncio.create_task(self._execute(sa_task))
        return sa_task

    async def _execute(self, sa_task: SubAgentTask):
        """Execute sub-agent task."""
        sa_task.status = "running"
        try:
            # Container-isolated execution
            if sa_task.container_isolated:
                try:
                    from breadmind.core.container import ContainerExecutor
                    executor = ContainerExecutor()
                    result = await executor.run_subagent(sa_task.task)
                    if result.error:
                        sa_task.result = f"Container error: {result.error}"
                        sa_task.status = "failed"
                    else:
                        sa_task.result = result.stdout
                        sa_task.status = "completed"
                except Exception as e:
                    sa_task.result = f"Container isolation failed: {e}"
                    sa_task.status = "failed"
                    logger.error(f"Sub-agent {sa_task.id} container execution failed: {e}")
                return

            if self._message_handler:
                if asyncio.iscoroutinefunction(self._message_handler):
                    result = await self._message_handler(
                        sa_task.task, user="subagent", channel=f"subagent:{sa_task.id}"
                    )
                else:
                    result = self._message_handler(
                        sa_task.task, user="subagent", channel=f"subagent:{sa_task.id}"
                    )
                sa_task.result = str(result)
                sa_task.status = "completed"
            else:
                sa_task.result = "No message handler available"
                sa_task.status = "failed"
        except Exception as e:
            sa_task.result = f"Error: {e}"
            sa_task.status = "failed"
            logger.error(f"Sub-agent {sa_task.id} failed: {e}")
        finally:
            sa_task.completed_at = datetime.now(timezone.utc)

    def get_task(self, task_id: str) -> dict | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return {
            "id": task.id, "parent_id": task.parent_id, "task": task.task,
            "status": task.status, "result": task.result,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "model": task.model,
        }

    def list_tasks(self, limit: int = 20) -> list[dict]:
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)[:limit]
        return [self.get_task(t.id) for t in tasks]

    def get_status(self) -> dict:
        statuses = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for t in self._tasks.values():
            statuses[t.status] = statuses.get(t.status, 0) + 1
        return {"total": len(self._tasks), **statuses}
