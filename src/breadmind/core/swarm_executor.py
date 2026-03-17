"""Swarm task decomposition, execution, and result aggregation."""
import asyncio
import logging
import time
from typing import Any

from breadmind.core.swarm import (
    DEFAULT_ROLES,
    SwarmContext,
    SwarmMember,
    SwarmResult,
    SwarmTask,
)

logger = logging.getLogger(__name__)


class SwarmCoordinator:
    """LLM-based coordinator that decomposes goals into tasks and aggregates results."""

    def __init__(self, message_handler=None):
        self._message_handler = message_handler

    async def decompose(self, goal: str, available_roles: set[str] | None = None) -> list[SwarmTask]:
        """Use LLM to decompose a goal into subtasks with role assignments."""
        roles_to_show = available_roles if available_roles else DEFAULT_ROLES.keys()
        decompose_prompt = (
            f"Decompose this goal into 2-5 concrete subtasks. For each task, specify which expert role should handle it.\n\n"
            f"Available roles: {', '.join(roles_to_show)}\n\n"
            f"Goal: {goal}\n\n"
            f"Respond in this exact format (one task per line):\n"
            f"TASK|<role>|<description>|<depends_on_task_numbers_comma_separated_or_none>\n\n"
            f"Example:\n"
            f"TASK|k8s_expert|Check pod health and resource usage|none\n"
            f"TASK|proxmox_expert|Check VM resource usage|none\n"
            f"TASK|performance_analyst|Compare and analyze both results|1,2\n\n"
            f"Output ONLY the TASK lines, no other text."
        )

        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    response = await self._message_handler(
                        decompose_prompt, user="swarm_coordinator", channel="swarm:decompose"
                    )
                else:
                    response = self._message_handler(
                        decompose_prompt, user="swarm_coordinator", channel="swarm:decompose"
                    )
            except Exception as e:
                logger.error(f"Failed to decompose goal: {e}")
                # Fallback: single general task
                return [SwarmTask(id="t1", description=goal, role="general")]
        else:
            return [SwarmTask(id="t1", description=goal, role="general")]

        return self._parse_tasks(str(response), available_roles=available_roles)

    def _parse_tasks(self, response: str, available_roles: set[str] | None = None) -> list[SwarmTask]:
        """Parse LLM response into SwarmTasks."""
        tasks: list[SwarmTask] = []
        task_num = 0
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line.startswith("TASK|"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            task_num += 1
            role = parts[1].strip()
            description = parts[2].strip()
            depends_str = parts[3].strip() if len(parts) > 3 else "none"

            depends_on = []
            if depends_str.lower() != "none":
                for dep in depends_str.split(","):
                    dep = dep.strip()
                    if dep.isdigit():
                        depends_on.append(f"t{dep}")

            if available_roles is not None:
                if role not in available_roles:
                    role = "general"
            elif role not in DEFAULT_ROLES:
                role = "general"

            tasks.append(SwarmTask(
                id=f"t{task_num}",
                description=description,
                role=role,
                depends_on=depends_on,
            ))

        if not tasks:
            tasks.append(SwarmTask(id="t1", description=response, role="general"))

        return tasks

    async def aggregate(self, goal: str, results: dict[str, str], task_roles: dict[str, str] | None = None) -> str:
        """Aggregate results from multiple tasks into a final answer."""
        aggregate_prompt = (
            f"You are aggregating results from multiple expert agents.\n\n"
            f"Original goal: {goal}\n\n"
            f"Results from each subtask:\n"
        )
        for task_id, result in results.items():
            role_label = f" (role: {task_roles[task_id]})" if task_roles and task_id in task_roles else ""
            aggregate_prompt += f"\n--- {task_id}{role_label} ---\n{result}\n"

        aggregate_prompt += (
            "\nProvide a comprehensive, unified analysis using the following structure:\n\n"
            "## Executive Summary\n"
            "A 2-3 sentence high-level overview of the overall infrastructure state.\n\n"
            "## Key Findings\n"
            "Group findings by severity. For each finding, include which role/agent reported it.\n\n"
            "### Critical\n"
            "- [role] Finding description and impact\n\n"
            "### Warning\n"
            "- [role] Finding description and potential risk\n\n"
            "### OK\n"
            "- [role] Verified healthy items (brief)\n\n"
            "## Recommended Actions\n"
            "Numbered list of prioritized actions, most urgent first.\n"
        )

        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    return await self._message_handler(
                        aggregate_prompt, user="swarm_coordinator", channel="swarm:aggregate"
                    )
                else:
                    return self._message_handler(
                        aggregate_prompt, user="swarm_coordinator", channel="swarm:aggregate"
                    )
            except Exception as e:
                logger.error(f"Failed to aggregate results: {e}")
                return "\n\n".join(f"[{tid}] {r}" for tid, r in results.items())
        else:
            return "\n\n".join(f"[{tid}] {r}" for tid, r in results.items())


class SwarmExecutor:
    """Executes swarm tasks: dependency resolution, parallel dispatch, tracking, and reflection."""

    def __init__(
        self,
        coordinator: SwarmCoordinator,
        roles: dict[str, SwarmMember],
        message_handler=None,
        tracker=None,
        skill_store=None,
        retriever=None,
    ):
        self._coordinator = coordinator
        self._roles = roles
        self._message_handler = message_handler
        self._tracker = tracker
        self._skill_store = skill_store
        self._retriever = retriever
        self._task_complete_count = 0

    async def execute(self, swarm: SwarmResult, roles_filter: list[str] | None = None,
                      team_builder=None):
        """Execute a swarm: decompose -> dispatch -> aggregate."""
        swarm.status = "running"
        try:
            # Phase 0: Build optimal team
            if team_builder:
                try:
                    team_plan = await team_builder.build_team(swarm.goal)
                    logger.info(f"TeamBuilder selected roles: {team_plan.selected_roles}, created: {team_plan.created_roles}")
                except Exception as e:
                    logger.error(f"TeamBuilder failed, proceeding with defaults: {e}")

            # Phase 1: Decompose goal into tasks
            available_roles = set(self._roles.keys())
            tasks = await self._coordinator.decompose(swarm.goal, available_roles=available_roles)

            # Filter by requested roles if specified
            if roles_filter:
                tasks = [t for t in tasks if t.role in roles_filter] or tasks

            context = SwarmContext()
            for task in tasks:
                context.task_graph[task.id] = task
                swarm.tasks.append({
                    "id": task.id, "description": task.description,
                    "role": task.role, "depends_on": task.depends_on,
                    "status": task.status,
                })

            # Phase 2: Execute tasks respecting dependencies
            results = await self._run_task_graph(swarm, tasks)

            # Phase 3: Aggregate results
            if results:
                task_roles = {t.id: t.role for t in tasks}
                swarm.final_result = await self._coordinator.aggregate(
                    swarm.goal, results, task_roles=task_roles
                )
            else:
                swarm.final_result = "No tasks completed successfully."

            # Phase 3.5: Self-reflection
            await self._reflect(swarm)

            swarm.status = "completed"

        except Exception as e:
            swarm.status = "failed"
            swarm.error = str(e)
            logger.error(f"Swarm {swarm.id} failed: {e}")
        finally:
            from datetime import datetime, timezone
            swarm.completed_at = datetime.now(timezone.utc)

    async def _run_task_graph(self, swarm: SwarmResult, tasks: list[SwarmTask]) -> dict[str, str]:
        """Execute tasks respecting dependency order, running independent tasks in parallel."""
        results: dict[str, str] = {}
        completed_ids: set[str] = set()

        while len(completed_ids) < len(tasks):
            ready = [
                t for t in tasks
                if t.id not in completed_ids
                and t.status == "pending"
                and all(d in completed_ids for d in t.depends_on)
            ]

            if not ready:
                stuck = [t for t in tasks if t.id not in completed_ids and t.status == "pending"]
                if stuck:
                    for t in stuck:
                        t.status = "failed"
                        t.error = "Dependencies not met"
                        completed_ids.add(t.id)
                    break
                break

            async def run_task(task: SwarmTask) -> None:
                t_start = time.monotonic()
                task.status = "running"
                self._update_swarm_task(swarm, task)
                try:
                    member = self._roles.get(task.role, DEFAULT_ROLES["general"])
                    prompt = f"[Role: {member.role}]\n{member.system_prompt}\n\nTask: {task.description}"
                    if task.depends_on:
                        prompt += "\n\nPrevious results:"
                        for dep_id in task.depends_on:
                            if dep_id in results:
                                prompt += f"\n--- From {dep_id} ---\n{results[dep_id][:2000]}"

                    if self._message_handler:
                        if asyncio.iscoroutinefunction(self._message_handler):
                            result = await self._message_handler(
                                prompt, user=f"swarm:{task.role}",
                                channel=f"swarm:{swarm.id}:{task.id}"
                            )
                        else:
                            result = self._message_handler(
                                prompt, user=f"swarm:{task.role}",
                                channel=f"swarm:{swarm.id}:{task.id}"
                            )
                    else:
                        result = f"No message handler available for task: {task.description}"

                    task.result = str(result)
                    task.status = "completed"
                    results[task.id] = task.result
                except Exception as e:
                    task.error = str(e)
                    task.status = "failed"
                    results[task.id] = f"Error: {e}"
                    logger.error(f"Swarm task {task.id} failed: {e}")
                finally:
                    completed_ids.add(task.id)
                    self._update_swarm_task(swarm, task)
                    await self._post_task_hooks(task, tasks, t_start)

            await asyncio.gather(*[run_task(t) for t in ready])

        return results

    async def _post_task_hooks(self, task: SwarmTask, all_tasks: list[SwarmTask],
                               t_start: float):
        """Run tracker and retriever hooks after a task completes."""
        if self._tracker:
            elapsed_ms = (time.monotonic() - t_start) * 1000
            await self._tracker.record_task_result(
                role=task.role,
                task_desc=task.description,
                success=(task.status == "completed"),
                duration_ms=elapsed_ms,
                result_summary=(task.result[:200] if task.result else task.error[:200]),
            )
            self._task_complete_count += 1
            if self._task_complete_count % 10 == 0 and self._skill_store:
                try:
                    recent = [
                        {"role": t.role, "description": t.description,
                         "success": t.status == "completed"}
                        for t in all_tasks if t.status in ("completed", "failed")
                    ]
                    patterns = await self._skill_store.detect_patterns(recent, self._message_handler)
                    if patterns:
                        logger.info(f"Detected {len(patterns)} skill patterns from recent tasks")
                except Exception as e:
                    logger.error(f"Pattern detection failed: {e}")

        if self._retriever:
            try:
                await self._retriever.index_task_result(
                    role=task.role,
                    task_desc=task.description,
                    result_summary=(task.result[:200] if task.result else task.error[:200]),
                    success=(task.status == "completed"),
                )
            except Exception as e:
                logger.error(f"Failed to index task result: {e}")

    async def _reflect(self, swarm: SwarmResult):
        """Self-reflection: extract lessons learned from completed swarm."""
        if not self._message_handler or not swarm.final_result:
            return
        try:
            reflection_prompt = (
                f"Reflect on this completed task and extract key lessons learned.\n\n"
                f"Goal: {swarm.goal}\n"
                f"Result summary: {swarm.final_result[:500]}\n\n"
                f"What are the key takeaways? What should be remembered for future similar tasks?\n"
                f"Respond concisely in 2-3 bullet points."
            )
            if asyncio.iscoroutinefunction(self._message_handler):
                reflection = await self._message_handler(
                    reflection_prompt, user="swarm_reflection", channel=f"swarm:{swarm.id}:reflect"
                )
            else:
                reflection = self._message_handler(
                    reflection_prompt, user="swarm_reflection", channel=f"swarm:{swarm.id}:reflect"
                )

            if self._retriever and reflection:
                await self._retriever.index_task_result(
                    role="swarm_reflection",
                    task_desc=f"Reflection on: {swarm.goal[:100]}",
                    result_summary=str(reflection)[:500],
                    success=True,
                )
        except Exception as e:
            logger.warning(f"Swarm reflection failed: {e}")

    @staticmethod
    def _update_swarm_task(swarm: SwarmResult, task: SwarmTask):
        """Update task status in swarm result."""
        for t in swarm.tasks:
            if t["id"] == task.id:
                t["status"] = task.status
                if task.result:
                    t["result"] = task.result[:500]
                if task.error:
                    t["error"] = task.error
                break
