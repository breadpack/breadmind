"""DAGExecutor: executes a TaskDAG in topological order with parallel batches."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from breadmind.core.planner import TaskDAG, TaskNode
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.core.subagent import SubAgentResult
from breadmind.core.events import get_event_bus, Event, EventType

logger = logging.getLogger("breadmind.dag_executor")

_MAX_CONCURRENT = 5

_DIFFICULTY_TIMEOUT = {
    "low": 60,
    "medium": 180,
    "high": 600,
}

SubAgentFactory = Callable[[TaskNode, dict[str, str]], Awaitable[SubAgentResult]]


class DAGExecutor:
    """Executes TaskDAG nodes in dependency order, parallelizing independent nodes."""

    def __init__(
        self,
        subagent_factory: SubAgentFactory,
        evaluator: ResultEvaluator,
        max_concurrent: int = _MAX_CONCURRENT,
        progress_callback: Callable | None = None,
    ) -> None:
        self._spawn = subagent_factory
        self._evaluator = evaluator
        self._max_concurrent = max_concurrent
        self._progress = progress_callback
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def execute(self, dag: TaskDAG) -> dict[str, SubAgentResult]:
        """Execute all nodes in the DAG. Returns {task_id: SubAgentResult}."""
        results: dict[str, SubAgentResult] = {}
        completed: set[str] = set()
        failed: set[str] = set()
        all_ids = set(dag.nodes.keys())

        while completed | failed != all_ids:
            ready = [
                dag.nodes[nid]
                for nid in all_ids - completed - failed
                if all(dep in completed for dep in dag.nodes[nid].depends_on)
            ]

            if not ready:
                for nid in all_ids - completed - failed:
                    results[nid] = SubAgentResult(
                        task_id=nid, success=False,
                        output="[success=False] Skipped: dependency failed",
                    )
                    failed.add(nid)
                break

            await self._notify_batch_start([n.id for n in ready])

            batch_results = await asyncio.gather(
                *[self._run_node(node, dag) for node in ready],
                return_exceptions=True,
            )

            for node, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    logger.error("SubAgent %s raised exception: %s", node.id, result)
                    sr = SubAgentResult(
                        task_id=node.id, success=False,
                        output=f"[success=False] Exception: {result}",
                    )
                    results[node.id] = sr
                    failed.add(node.id)
                    continue

                results[node.id] = result
                eval_result = self._evaluator.evaluate(result.output, node.expected_output)

                if eval_result.status == "normal":
                    dag.context[node.id] = result.output
                    completed.add(node.id)
                else:
                    failed.add(node.id)

            await self._notify_batch_end([n.id for n in ready])

        return results

    async def _run_node(self, node: TaskNode, dag: TaskDAG) -> SubAgentResult:
        timeout = _DIFFICULTY_TIMEOUT.get(node.difficulty, 180)
        async with self._semaphore:
            await self._notify_subagent_start(node.id, node.role)
            try:
                result = await asyncio.wait_for(
                    self._spawn(node, dict(dag.context)),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                result = SubAgentResult(
                    task_id=node.id, success=False,
                    output=f"[success=False] Tool execution timed out after {timeout}s.",
                )
            await self._notify_subagent_end(node.id, result.success)
            return result

    async def _notify_batch_start(self, node_ids: list[str]) -> None:
        if self._progress:
            await self._progress("dag_batch_start", str(node_ids))
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.DAG_BATCH_START, data={"nodes": node_ids}, source="dag_executor",
            ))
        except Exception:
            pass

    async def _notify_batch_end(self, node_ids: list[str]) -> None:
        if self._progress:
            await self._progress("dag_batch_end", str(node_ids))
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.DAG_BATCH_END, data={"nodes": node_ids}, source="dag_executor",
            ))
        except Exception:
            pass

    async def _notify_subagent_start(self, task_id: str, role: str) -> None:
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.SUBAGENT_START, data={"task_id": task_id, "role": role}, source="dag_executor",
            ))
        except Exception:
            pass

    async def _notify_subagent_end(self, task_id: str, success: bool) -> None:
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.SUBAGENT_END, data={"task_id": task_id, "success": success}, source="dag_executor",
            ))
        except Exception:
            pass
