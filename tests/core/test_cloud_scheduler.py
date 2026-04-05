"""Tests for Cloud Scheduled Tasks."""

from __future__ import annotations

import pytest

from breadmind.core.cloud_scheduler import CloudScheduler, CloudTask, CloudTaskStatus


class TestCloudTask:
    def test_defaults(self):
        t = CloudTask()
        assert len(t.id) == 12
        assert t.status == CloudTaskStatus.PENDING
        assert t.result is None

    def test_status_enum(self):
        assert CloudTaskStatus.PENDING == "pending"
        assert CloudTaskStatus.COMPLETED == "completed"


class TestCloudScheduler:
    async def test_schedule_once(self):
        sched = CloudScheduler(endpoint="http://worker:8080")
        task = await sched.schedule("run backup", schedule="once")
        assert task.prompt == "run backup"
        assert task.schedule == "once"
        assert task.status == CloudTaskStatus.PENDING

    async def test_schedule_cron(self):
        sched = CloudScheduler()
        task = await sched.schedule("daily check", schedule="0 8 * * 1")
        assert task.schedule == "0 8 * * 1"

    async def test_schedule_invalid_cron_raises(self):
        sched = CloudScheduler()
        with pytest.raises(ValueError, match="Invalid schedule"):
            await sched.schedule("bad", schedule="not-a-cron")

    async def test_cancel_task(self):
        sched = CloudScheduler()
        task = await sched.schedule("cancel me")
        assert await sched.cancel(task.id) is True
        status = await sched.get_status(task.id)
        assert status is not None
        assert status.status == CloudTaskStatus.CANCELLED

    async def test_cancel_nonexistent(self):
        sched = CloudScheduler()
        assert await sched.cancel("nonexistent") is False

    async def test_cancel_completed_task(self):
        sched = CloudScheduler()
        task = await sched.schedule("done task")
        await sched.execute_remote(task)
        assert await sched.cancel(task.id) is False

    async def test_list_tasks_all(self):
        sched = CloudScheduler()
        await sched.schedule("a")
        await sched.schedule("b")
        tasks = await sched.list_tasks()
        assert len(tasks) == 2

    async def test_list_tasks_filtered(self):
        sched = CloudScheduler()
        t1 = await sched.schedule("a")
        await sched.schedule("b")
        await sched.execute_remote(t1)
        completed = await sched.list_tasks(status=CloudTaskStatus.COMPLETED)
        assert len(completed) == 1

    async def test_execute_remote(self):
        sched = CloudScheduler()
        task = await sched.schedule("do something")
        result = await sched.execute_remote(task)
        assert result == "executed:do something"
        assert task.status == CloudTaskStatus.COMPLETED
        assert task.last_run is not None

    async def test_get_status_nonexistent(self):
        sched = CloudScheduler()
        assert await sched.get_status("nope") is None
