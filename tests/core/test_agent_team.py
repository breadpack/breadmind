"""Tests for agent team orchestration."""
from __future__ import annotations

import asyncio


from breadmind.core.agent_team import (
    AgentTeam,
    Mailbox,
    TaskBoard,
    TaskStatus,
    TeammateConfig,
)


async def test_task_board_add_task() -> None:
    board = TaskBoard()
    task = await board.add_task("Build feature", "Implement X")
    assert task.title == "Build feature"
    assert task.description == "Implement X"
    assert task.status == TaskStatus.PENDING
    assert task.id.startswith("task_")
    assert task.assigned_to is None


async def test_task_board_claim_task() -> None:
    board = TaskBoard()
    await board.add_task("Task A")
    await board.add_task("Task B")

    claimed = await board.claim_task("agent_1")
    assert claimed is not None
    assert claimed.status == TaskStatus.IN_PROGRESS
    assert claimed.assigned_to == "agent_1"
    assert claimed.title == "Task A"

    claimed2 = await board.claim_task("agent_2")
    assert claimed2 is not None
    assert claimed2.title == "Task B"


async def test_task_board_complete_task() -> None:
    board = TaskBoard()
    task = await board.add_task("Task A")
    await board.claim_task("agent_1")
    await board.complete_task(task.id, "done")

    assert task.status == TaskStatus.COMPLETED
    assert task.result == "done"
    assert task.completed_at is not None


async def test_task_board_dependency_blocking() -> None:
    board = TaskBoard()
    t1 = await board.add_task("Task 1")
    await board.add_task("Task 2", depends_on=[t1.id])

    # Agent should only be able to claim t1 since t2 depends on it
    claimed = await board.claim_task("agent_1")
    assert claimed is not None
    assert claimed.id == t1.id

    # t2 should not be claimable yet
    claimed2 = await board.claim_task("agent_2")
    assert claimed2 is None


async def test_task_board_auto_unblock() -> None:
    board = TaskBoard()
    t1 = await board.add_task("Task 1")
    t2 = await board.add_task("Task 2", depends_on=[t1.id])

    # Manually set t2 to BLOCKED to test unblock logic
    t2.status = TaskStatus.BLOCKED

    # Claim and complete t1
    await board.claim_task("agent_1")
    await board.complete_task(t1.id, "done")

    # t2 should now be unblocked (PENDING)
    assert t2.status == TaskStatus.PENDING

    # Now agent can claim t2
    claimed = await board.claim_task("agent_2")
    assert claimed is not None
    assert claimed.id == t2.id


async def test_task_board_all_done() -> None:
    board = TaskBoard()
    t1 = await board.add_task("Task 1")
    t2 = await board.add_task("Task 2")

    assert not board.all_done

    await board.claim_task("a1")
    await board.complete_task(t1.id, "ok")
    assert not board.all_done

    await board.claim_task("a2")
    await board.complete_task(t2.id, "ok")
    assert board.all_done


async def test_mailbox_send_and_receive() -> None:
    mailbox = Mailbox()
    await mailbox.send("agent_1", "agent_2", "hello")
    await mailbox.send("agent_1", "agent_2", "world")

    messages = await mailbox.receive("agent_2")
    assert len(messages) == 2
    assert messages[0].content == "hello"
    assert messages[1].content == "world"
    assert messages[0].from_agent == "agent_1"

    # Messages should be consumed
    messages2 = await mailbox.receive("agent_2")
    assert len(messages2) == 0


async def test_mailbox_broadcast() -> None:
    mailbox = Mailbox()
    # Initialize mailboxes by sending a direct message first
    await mailbox.send("agent_1", "agent_2", "init")
    await mailbox.send("agent_1", "agent_3", "init")
    # Consume init messages
    await mailbox.receive("agent_2")
    await mailbox.receive("agent_3")

    # Broadcast
    await mailbox.send("agent_1", "*", "broadcast msg")

    msgs_2 = await mailbox.receive("agent_2")
    msgs_3 = await mailbox.receive("agent_3")
    assert any(m.content == "broadcast msg" for m in msgs_2)
    assert any(m.content == "broadcast msg" for m in msgs_3)


async def test_agent_team_add_remove_teammate() -> None:
    team = AgentTeam("test-team")
    config = TeammateConfig(agent_id="a1", name="Alice", role="implementer")
    team.add_teammate(config)

    status = team.get_status()
    assert "a1" in status["teammates"]

    removed = team.remove_teammate("a1")
    assert removed is True

    removed2 = team.remove_teammate("nonexistent")
    assert removed2 is False


async def test_agent_team_run_and_complete() -> None:
    team = AgentTeam("test-team")
    team.add_teammate(TeammateConfig(agent_id="a1", name="Alice", role="worker"))
    team.add_teammate(TeammateConfig(agent_id="a2", name="Bob", role="worker"))

    await team.task_board.add_task("Task 1")
    await team.task_board.add_task("Task 2")
    await team.task_board.add_task("Task 3")

    async def handler(agent_id: str, task: object, mailbox: object) -> str:
        await asyncio.sleep(0.01)
        return f"done by {agent_id}"

    await team.start(handler)
    result = await team.wait_until_done(timeout=10)

    assert result["team"] == "test-team"
    assert result["progress"].get("completed", 0) == 3
    assert all(t["status"] == "completed" for t in result["tasks"])


async def test_agent_team_status() -> None:
    team = AgentTeam("my-team", lead_id="lead_1")
    team.add_teammate(TeammateConfig(agent_id="a1", name="Alice", role="coder"))

    status = team.get_status()
    assert status["name"] == "my-team"
    assert status["lead"] == "lead_1"
    assert status["running"] is False
    assert "a1" in status["teammates"]


async def test_task_progress_tracking() -> None:
    board = TaskBoard()
    t1 = await board.add_task("T1")
    await board.add_task("T2")
    await board.add_task("T3")

    progress = board.get_progress()
    assert progress["pending"] == 3

    await board.claim_task("a1")
    await board.complete_task(t1.id, "ok")

    progress = board.get_progress()
    assert progress.get("completed", 0) == 1
    assert progress.get("pending", 0) == 2

    assert board.get_pending_count() == 2


async def test_task_fail_handling() -> None:
    team = AgentTeam("fail-team")
    team.add_teammate(TeammateConfig(agent_id="a1", name="Alice", role="worker"))

    await team.task_board.add_task("Failing task")

    async def failing_handler(agent_id: str, task: object, mailbox: object) -> str:
        raise ValueError("something broke")

    await team.start(failing_handler)
    result = await team.wait_until_done(timeout=5)

    assert result["progress"].get("failed", 0) == 1
    assert "FAILED" in result["tasks"][0]["result"]
