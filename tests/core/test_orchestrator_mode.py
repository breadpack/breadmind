"""Tests for Orchestrator Mode (multi-agent subtask decomposition)."""

from __future__ import annotations

import pytest

from breadmind.core.orchestrator_mode import (
    AgentRole,
    OrchestratorMode,
    OrchestratorPlan,
    SubTask,
)


class TestSubTask:
    def test_defaults(self):
        st = SubTask()
        assert len(st.id) == 8
        assert st.status == "pending"
        assert st.assigned_to == AgentRole.CODER


class TestOrchestratorPlan:
    def test_ready_tasks_no_deps(self):
        plan = OrchestratorPlan(
            task_description="test",
            subtasks=[SubTask(id="a"), SubTask(id="b")],
        )
        ready = plan.ready_tasks()
        assert len(ready) == 2

    def test_ready_tasks_with_deps(self):
        plan = OrchestratorPlan(
            task_description="test",
            subtasks=[
                SubTask(id="a", status="done"),
                SubTask(id="b", depends_on=["a"]),
                SubTask(id="c", depends_on=["b"]),
            ],
        )
        ready = plan.ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "b"

    def test_is_complete(self):
        plan = OrchestratorPlan(
            task_description="test",
            subtasks=[
                SubTask(id="a", status="done"),
                SubTask(id="b", status="failed"),
            ],
        )
        assert plan.is_complete() is True

    def test_is_not_complete(self):
        plan = OrchestratorPlan(
            task_description="test",
            subtasks=[
                SubTask(id="a", status="done"),
                SubTask(id="b", status="pending"),
            ],
        )
        assert plan.is_complete() is False


class TestOrchestratorMode:
    def test_create_plan(self):
        orch = OrchestratorMode()
        plan = orch.create_plan("Build a REST API")
        assert plan.task_description == "Build a REST API"
        assert len(plan.subtasks) >= 3

    def test_decompose_produces_planner_coder_reviewer(self):
        orch = OrchestratorMode()
        subtasks = orch.decompose("Implement user authentication")
        roles = [st.assigned_to for st in subtasks]
        assert AgentRole.PLANNER in roles
        assert AgentRole.CODER in roles
        assert AgentRole.REVIEWER in roles

    def test_decompose_debug_task(self):
        orch = OrchestratorMode()
        subtasks = orch.decompose("Fix the login bug")
        roles = [st.assigned_to for st in subtasks]
        assert AgentRole.DEBUGGER in roles

    def test_complete_subtask_returns_ready(self):
        orch = OrchestratorMode()
        plan = orch.create_plan("Build feature")
        first = plan.ready_tasks()
        assert len(first) >= 1
        newly_ready = orch.complete_subtask(first[0].id, "done planning")
        assert len(newly_ready) >= 1

    def test_fail_subtask(self):
        orch = OrchestratorMode()
        plan = orch.create_plan("Build feature")
        first = plan.ready_tasks()[0]
        orch.fail_subtask(first.id, "something broke")
        assert first.status == "failed"
        assert first.result == "something broke"

    def test_assign_role(self):
        orch = OrchestratorMode()
        plan = orch.create_plan("Build feature")
        st = plan.subtasks[0]
        orch.assign(st.id, AgentRole.DEBUGGER)
        assert st.assigned_to == AgentRole.DEBUGGER

    def test_complete_unknown_raises(self):
        orch = OrchestratorMode()
        with pytest.raises(KeyError):
            orch.complete_subtask("nonexistent", "result")

    def test_fail_unknown_raises(self):
        orch = OrchestratorMode()
        with pytest.raises(KeyError):
            orch.fail_subtask("nonexistent", "error")

    def test_assign_unknown_raises(self):
        orch = OrchestratorMode()
        with pytest.raises(KeyError):
            orch.assign("nonexistent", AgentRole.CODER)
