"""Orchestrator: coordinates Planner, DAGExecutor, and SubAgents for complex tasks."""
from __future__ import annotations

import logging
from typing import Callable

from breadmind.llm.base import LLMProvider, LLMMessage
from breadmind.core.planner import Planner, TaskDAG, TaskNode
from breadmind.core.dag_executor import DAGExecutor
from breadmind.core.subagent import SubAgent, SubAgentResult
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.core.role_registry import RoleRegistry
from breadmind.core.events import get_event_bus, Event, EventType

logger = logging.getLogger("breadmind.orchestrator")

_MAX_RETRIES = 2
_MAX_REPLANS = 1
_DIFFICULTY_TURNS = {"low": 3, "medium": 5, "high": 10}


class Orchestrator:
    """Top-level coordinator: plans, executes DAG, handles failures, summarizes."""

    def __init__(
        self,
        provider: LLMProvider,
        role_registry: RoleRegistry,
        evaluator: ResultEvaluator,
        tool_registry: object,
        progress_callback: Callable | None = None,
    ) -> None:
        self._provider = provider
        self._roles = role_registry
        self._evaluator = evaluator
        self._tool_registry = tool_registry
        self._progress = progress_callback
        self._planner = Planner(provider=provider, role_registry=role_registry)

    async def run(self, message: str, user: str, channel: str) -> str:
        await self._emit(EventType.ORCHESTRATOR_START, {"message": message, "user": user})

        if self._progress:
            await self._progress("orchestrator", "Planning task decomposition...")
        dag = await self._planner.plan(message)
        logger.info("Planner created DAG with %d nodes for: %s", len(dag.nodes), message[:100])

        results = await self._execute_with_fallback(dag)

        if self._progress:
            await self._progress("orchestrator", "Summarizing results...")
        summary = await self._summarize(dag, results)

        await self._emit(EventType.ORCHESTRATOR_END, {
            "total_tasks": len(dag.nodes),
            "succeeded": sum(1 for r in results.values() if r.success),
            "failed": sum(1 for r in results.values() if not r.success),
        })

        return summary

    async def _execute_with_fallback(self, dag: TaskDAG) -> dict[str, SubAgentResult]:
        executor = DAGExecutor(
            subagent_factory=self._create_subagent_factory(),
            evaluator=self._evaluator,
            progress_callback=self._progress,
        )

        results = await executor.execute(dag)

        failed_tasks = {tid: r for tid, r in results.items() if not r.success}

        for tid, result in failed_tasks.items():
            node = dag.nodes.get(tid)
            if node is None:
                continue

            # Retry
            for attempt in range(node.max_retries):
                logger.info("Retrying task %s (attempt %d/%d)", tid, attempt + 1, node.max_retries)
                retry_result = await self._retry_single(node, dag.context)
                if retry_result.success:
                    results[tid] = retry_result
                    dag.context[tid] = retry_result.output
                    break
                results[tid] = retry_result

            if results[tid].success:
                continue

            # Replan
            eval_result = self._evaluator.evaluate(results[tid].output, node.expected_output)
            logger.info("Replanning for failed task %s: %s", tid, eval_result.failure_reason)
            await self._emit(EventType.ORCHESTRATOR_REPLAN, {"failed_task": tid, "reason": eval_result.failure_reason})

            alt_dag = await self._planner.replan(dag.goal, dag, tid, eval_result.failure_reason)
            if alt_dag.nodes:
                alt_executor = DAGExecutor(
                    subagent_factory=self._create_subagent_factory(),
                    evaluator=self._evaluator,
                    progress_callback=self._progress,
                )
                alt_results = await alt_executor.execute(alt_dag)

                for alt_tid, alt_result in alt_results.items():
                    if alt_result.success:
                        results[alt_tid] = alt_result
                        dag.context[alt_tid] = alt_result.output
                        results[tid] = SubAgentResult(
                            task_id=tid, success=True,
                            output=f"Replaced by {alt_tid}: {alt_result.output}",
                            turns_used=alt_result.turns_used,
                        )
                        break

        return results

    def _create_subagent_factory(self):
        roles = self._roles
        provider = self._provider
        tool_registry = self._tool_registry

        async def factory(node: TaskNode, context: dict[str, str]) -> SubAgentResult:
            system_prompt = roles.get_prompt(node.role)
            tool_names = node.tools or roles.get_tools(node.role)
            max_turns = _DIFFICULTY_TURNS.get(node.difficulty, 5)

            all_tools = tool_registry.get_all_definitions() if hasattr(tool_registry, "get_all_definitions") else []
            tools = [t for t in all_tools if t.get("name") in tool_names] if tool_names else all_tools[:20]

            agent = SubAgent(
                task_id=node.id,
                description=node.description,
                role=node.role,
                provider=provider,
                tools=tools,
                system_prompt=system_prompt,
                max_turns=max_turns,
                tool_executor=tool_registry.execute if hasattr(tool_registry, "execute") else None,
            )
            return await agent.run(context=context)

        return factory

    async def _retry_single(self, node: TaskNode, context: dict[str, str]) -> SubAgentResult:
        factory = self._create_subagent_factory()
        return await factory(node, context)

    async def _summarize(self, dag: TaskDAG, results: dict[str, SubAgentResult]) -> str:
        results_text = []
        for tid, node in dag.nodes.items():
            result = results.get(tid)
            status = "SUCCESS" if result and result.success else "FAILED"
            output = (result.output[:500] if result else "No result")
            results_text.append(f"[{status}] {node.description}:\n{output}")

        messages = [
            LLMMessage(role="system", content=(
                "You are summarizing the results of a multi-step infrastructure task. "
                "Provide a clear, concise summary for the user. "
                "Highlight successes, failures, and any actions taken. "
                "Use the user's language (Korean if the goal is in Korean)."
            )),
            LLMMessage(role="user", content=(
                f"Goal: {dag.goal}\n\nResults:\n" + "\n\n".join(results_text)
            )),
        ]

        try:
            response = await self._provider.chat(messages=messages)
            return response.content or "\n".join(results_text)
        except Exception as e:
            logger.error("Summary generation failed: %s", e)
            return "\n".join(results_text)

    async def _emit(self, event_type: EventType, data: dict) -> None:
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=event_type, data=data, source="orchestrator",
            ))
        except Exception:
            pass
