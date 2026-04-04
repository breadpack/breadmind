"""v2 서브에이전트 Spawner: 재귀 spawn + 선언적 SwarmPlan."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from breadmind.core.protocols import AgentContext, AgentResponse

if TYPE_CHECKING:
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent

logger = logging.getLogger("breadmind.spawner")


@dataclass
class SwarmTask:
    id: str
    description: str
    role: str | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SwarmPlan:
    goal: str
    tasks: list[SwarmTask] = field(default_factory=list)


@dataclass
class SpawnResult:
    agent_id: str
    response: str
    success: bool = True


class Spawner:
    """재귀적 서브에이전트 spawn + SwarmPlan 실행."""

    def __init__(
        self,
        agent_factory: Any = None,
        max_depth: int = 5,
        max_concurrent: int = 5,
    ) -> None:
        self._factory = agent_factory
        self._max_depth = max_depth
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._children: dict[str, MessageLoopAgent] = {}

    async def spawn(
        self,
        prompt: str,
        ctx: AgentContext,
        tools: list[str] | None = None,
        isolation: str | None = None,
    ) -> SpawnResult:
        if ctx.depth >= self._max_depth:
            return SpawnResult(
                agent_id="",
                response=f"Max spawn depth ({self._max_depth}) reached.",
                success=False,
            )

        child_ctx = AgentContext(
            user=ctx.user,
            channel=ctx.channel,
            session_id=f"{ctx.session_id}:sub_{ctx.depth + 1}",
            parent_agent=ctx.session_id,
            depth=ctx.depth + 1,
            max_depth=self._max_depth,
            isolation=isolation,
        )

        if self._factory is None:
            return SpawnResult(agent_id="", response="No agent factory configured.", success=False)

        async with self._semaphore:
            try:
                child_agent = self._factory(tools=tools)
                response = await child_agent.handle_message(prompt, child_ctx)
                return SpawnResult(
                    agent_id=child_agent.agent_id,
                    response=response.content,
                    success=True,
                )
            except Exception as e:
                logger.error("Spawn failed: %s", e)
                return SpawnResult(agent_id="", response=str(e), success=False)

    async def spawn_child(
        self,
        parent: MessageLoopAgent,
        prompt: str,
        tools: list[str] | None = None,
    ) -> MessageLoopAgent:
        """parent의 컴포넌트를 공유하여 child MessageLoopAgent를 생성하고 추적."""
        from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent

        if self._factory is not None:
            child = self._factory(tools=tools)
        else:
            child = MessageLoopAgent(
                provider=parent._provider,
                prompt_builder=parent._prompt_builder,
                tool_registry=parent._tool_registry,
                safety_guard=parent._safety,
                max_turns=parent._max_turns,
                spawner_factory=parent._spawner_factory,
            )
        self._children[child.agent_id] = child
        return child

    async def send_to(self, target_id: str, message: str) -> str:
        """agent_id로 자식 에이전트를 찾아 메시지를 전송."""
        child = self._children.get(target_id)
        if child is None:
            raise KeyError(f"No child agent with id '{target_id}'")
        ctx = AgentContext(
            user="system",
            channel="internal",
            session_id=f"msg_{target_id}",
        )
        response: AgentResponse = await child.handle_message(message, ctx)
        return response.content

    async def execute_swarm(self, plan: SwarmPlan, ctx: AgentContext) -> dict[str, SpawnResult]:
        """SwarmPlan의 task를 의존성 순서로 실행."""
        results: dict[str, SpawnResult] = {}
        completed: set[str] = set()
        all_ids = {t.id for t in plan.tasks}
        task_map = {t.id: t for t in plan.tasks}

        while completed != all_ids:
            ready = [
                task_map[tid] for tid in all_ids - completed
                if all(d in completed for d in task_map[tid].depends_on)
            ]

            if not ready:
                # Stuck — remaining tasks have unmet deps
                for tid in all_ids - completed:
                    results[tid] = SpawnResult(
                        agent_id="", response="Skipped: dependency failed", success=False,
                    )
                break

            batch_results = await asyncio.gather(
                *[self._run_swarm_task(task, ctx, results) for task in ready],
                return_exceptions=True,
            )

            for task, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    results[task.id] = SpawnResult(agent_id="", response=str(result), success=False)
                else:
                    results[task.id] = result
                    if result.success:
                        completed.add(task.id)
                    else:
                        # Mark as done (failed) to prevent infinite loop
                        completed.add(task.id)

        return results

    async def _run_swarm_task(
        self, task: SwarmTask, ctx: AgentContext, prior_results: dict[str, SpawnResult],
    ) -> SpawnResult:
        # Build context from prior results
        context_parts = []
        for dep_id in task.depends_on:
            if dep_id in prior_results and prior_results[dep_id].success:
                context_parts.append(f"[Result from {dep_id}]: {prior_results[dep_id].response[:500]}")

        prompt = task.description
        if context_parts:
            prompt = "\n".join(context_parts) + "\n\n" + prompt

        return await self.spawn(prompt, ctx)
