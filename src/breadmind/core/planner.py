"""Planner: decomposes user requests into a TaskDAG via LLM call."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from breadmind.llm.base import LLMProvider, LLMMessage
from breadmind.core.role_registry import RoleRegistry

logger = logging.getLogger("breadmind.planner")


@dataclass
class TaskNode:
    id: str
    description: str
    role: str
    depends_on: list[str] = field(default_factory=list)
    difficulty: str = "medium"  # "low" | "medium" | "high"
    tools: list[str] = field(default_factory=list)
    expected_output: str = ""
    max_retries: int = 2


@dataclass
class TaskDAG:
    goal: str
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)


_PLANNER_PROMPT = """\
You are a task planner for BreadMind, an AI infrastructure agent.
Decompose the user's request into a TaskDAG: a directed acyclic graph of tasks.

## Available Roles
{role_summaries}

## Rules
- Each task has: id, description, role, depends_on (list of task IDs), difficulty (low/medium/high), expected_output.
- Tasks with no dependencies can run in parallel.
- Use the most specific role for each task.
- difficulty: low = simple query/status check, medium = analysis/config change, high = complex diagnosis/risky operation.
- Minimize the number of tasks. Combine trivially sequential steps into one task.

## Output Format
Respond with ONLY a JSON object:
{{"nodes": [{{"id": "task_1", "description": "...", "role": "...", "depends_on": [], "difficulty": "low", "expected_output": "..."}}]}}
"""


class Planner:
    def __init__(self, provider: LLMProvider, role_registry: RoleRegistry) -> None:
        self._provider = provider
        self._roles = role_registry

    async def plan(self, goal: str) -> TaskDAG:
        system_prompt = _PLANNER_PROMPT.format(role_summaries=self._roles.list_role_summaries())
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=goal),
        ]
        try:
            response = await self._provider.chat(messages=messages)
            return self._parse_response(goal, response.content or "")
        except Exception as e:
            logger.error("Planner failed: %s", e)
            return self._fallback_dag(goal)

    def _parse_response(self, goal: str, content: str) -> TaskDAG:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Planner returned invalid JSON, using fallback DAG")
            return self._fallback_dag(goal)
        nodes_data = data.get("nodes", [])
        if not nodes_data:
            return self._fallback_dag(goal)
        dag = TaskDAG(goal=goal)
        for n in nodes_data:
            node = TaskNode(
                id=n.get("id", f"task_{len(dag.nodes) + 1}"),
                description=n.get("description", ""),
                role=n.get("role", "general_analyst"),
                depends_on=n.get("depends_on", []),
                difficulty=n.get("difficulty", "medium"),
                expected_output=n.get("expected_output", ""),
                max_retries=n.get("max_retries", 2),
            )
            dag.nodes[node.id] = node
        return dag

    def _fallback_dag(self, goal: str) -> TaskDAG:
        dag = TaskDAG(goal=goal)
        dag.nodes["task_1"] = TaskNode(
            id="task_1", description=goal, role="general_analyst",
            difficulty="medium", expected_output="Task result",
        )
        return dag

    async def replan(self, goal: str, dag: TaskDAG, failed_task_id: str, failure_reason: str) -> TaskDAG:
        system_prompt = _PLANNER_PROMPT.format(role_summaries=self._roles.list_role_summaries())
        completed = {tid: ctx for tid, ctx in dag.context.items()}
        failed_node = dag.nodes.get(failed_task_id)
        replan_msg = (
            f"Original goal: {goal}\n\n"
            f"Completed tasks so far:\n"
            + "\n".join(f"- {tid}: {out[:200]}" for tid, out in completed.items())
            + f"\n\nFailed task: {failed_task_id} ({failed_node.description if failed_node else 'unknown'})\n"
            f"Failure reason: {failure_reason}\n\n"
            f"Generate replacement task(s) using a DIFFERENT approach. "
            f"Keep IDs unique (use task_alt_1, task_alt_2, etc.). "
            f"These tasks may depend on already-completed tasks: {list(completed.keys())}"
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=replan_msg),
        ]
        try:
            response = await self._provider.chat(messages=messages)
            return self._parse_response(goal, response.content or "")
        except Exception as e:
            logger.error("Replan failed: %s", e)
            return TaskDAG(goal=goal)
