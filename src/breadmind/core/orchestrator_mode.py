"""Orchestrator Mode — multi-agent subtask decomposition.

Breaks complex tasks into coordinated subtasks assigned to specialised
agent roles (planner, coder, debugger, reviewer).  Inspired by Kilo Code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from breadmind.utils.helpers import generate_short_id


class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    DEBUGGER = "debugger"
    REVIEWER = "reviewer"


@dataclass
class SubTask:
    id: str = field(default_factory=generate_short_id)
    description: str = ""
    assigned_to: AgentRole = AgentRole.CODER
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, done, failed
    result: str = ""


@dataclass
class OrchestratorPlan:
    task_description: str
    subtasks: list[SubTask] = field(default_factory=list)

    def ready_tasks(self) -> list[SubTask]:
        """Get tasks whose dependencies are all done."""
        done_ids = {st.id for st in self.subtasks if st.status == "done"}
        return [
            st
            for st in self.subtasks
            if st.status == "pending" and all(d in done_ids for d in st.depends_on)
        ]

    def is_complete(self) -> bool:
        return all(st.status in ("done", "failed") for st in self.subtasks)


# Keyword patterns for auto-decomposition role assignment
_DEBUG_PATTERN = re.compile(r"\b(fix|bug|debug|error|issue|broken)\b", re.IGNORECASE)
_REVIEW_PATTERN = re.compile(r"\b(review|validate|verify|check|test)\b", re.IGNORECASE)
_PLAN_PATTERN = re.compile(r"\b(plan|design|architect|outline)\b", re.IGNORECASE)


class OrchestratorMode:
    """Multi-agent subtask decomposition orchestrator.

    Breaks complex tasks into subtasks assigned to specialised agents:
    - Planner: designs the approach
    - Coder: implements code
    - Debugger: investigates and fixes issues
    - Reviewer: validates results
    """

    def __init__(self) -> None:
        self._plans: dict[str, OrchestratorPlan] = {}
        self._all_subtasks: dict[str, SubTask] = {}

    def create_plan(self, task_description: str) -> OrchestratorPlan:
        """Create an orchestration plan for a complex task."""
        subtasks = self.decompose(task_description)
        plan = OrchestratorPlan(
            task_description=task_description,
            subtasks=subtasks,
        )
        plan_id = generate_short_id()
        self._plans[plan_id] = plan
        for st in subtasks:
            self._all_subtasks[st.id] = st
        return plan

    def decompose(self, task_description: str) -> list[SubTask]:
        """Auto-decompose a task into subtasks based on keywords.

        Always produces at least a planning step and a review step,
        with implementation/debug steps in between based on content.
        """
        subtasks: list[SubTask] = []

        # 1. Planning step
        plan_task = SubTask(
            description=f"Plan approach for: {task_description}",
            assigned_to=AgentRole.PLANNER,
        )
        subtasks.append(plan_task)

        # 2. Core work — debug or implement
        if _DEBUG_PATTERN.search(task_description):
            work_task = SubTask(
                description=f"Debug/fix: {task_description}",
                assigned_to=AgentRole.DEBUGGER,
                depends_on=[plan_task.id],
            )
        else:
            work_task = SubTask(
                description=f"Implement: {task_description}",
                assigned_to=AgentRole.CODER,
                depends_on=[plan_task.id],
            )
        subtasks.append(work_task)

        # 3. Review step
        review_task = SubTask(
            description=f"Review results for: {task_description}",
            assigned_to=AgentRole.REVIEWER,
            depends_on=[work_task.id],
        )
        subtasks.append(review_task)

        return subtasks

    def assign(self, subtask_id: str, role: AgentRole) -> None:
        task = self._all_subtasks.get(subtask_id)
        if task is None:
            raise KeyError(f"Unknown subtask: {subtask_id}")
        task.assigned_to = role

    def complete_subtask(self, subtask_id: str, result: str) -> list[SubTask]:
        """Mark subtask complete, return newly ready tasks."""
        task = self._all_subtasks.get(subtask_id)
        if task is None:
            raise KeyError(f"Unknown subtask: {subtask_id}")
        task.status = "done"
        task.result = result

        # Find which plan this belongs to and return newly ready tasks
        for plan in self._plans.values():
            if any(st.id == subtask_id for st in plan.subtasks):
                return plan.ready_tasks()
        return []

    def fail_subtask(self, subtask_id: str, error: str) -> None:
        task = self._all_subtasks.get(subtask_id)
        if task is None:
            raise KeyError(f"Unknown subtask: {subtask_id}")
        task.status = "failed"
        task.result = error
