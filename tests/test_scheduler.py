import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from breadmind.core.scheduler import CronJob, HeartbeatTask, Scheduler
from breadmind.web.app import WebApp


# --- Scheduler unit tests ---


class TestCronJob:
    def test_create_cron_job(self):
        job = CronJob(id="j1", name="Morning report", schedule="0 9 * * *", task="Generate report")
        assert job.id == "j1"
        assert job.name == "Morning report"
        assert job.schedule == "0 9 * * *"
        assert job.task == "Generate report"
        assert job.enabled is True
        assert job.last_run is None
        assert job.next_run is None
        assert job.run_count == 0
        assert job.model is None

    def test_create_cron_job_with_model(self):
        job = CronJob(id="j2", name="Test", schedule="* * * * *", task="do stuff", model="gpt-4")
        assert job.model == "gpt-4"


class TestHeartbeatTask:
    def test_create_heartbeat(self):
        hb = HeartbeatTask(id="h1", name="Health check", interval_minutes=15, task="Check services")
        assert hb.id == "h1"
        assert hb.name == "Health check"
        assert hb.interval_minutes == 15
        assert hb.task == "Check services"
        assert hb.enabled is True
        assert hb.last_run is None
        assert hb.run_count == 0

    def test_default_interval(self):
        hb = HeartbeatTask(id="h2", name="Default")
        assert hb.interval_minutes == 30


class TestSchedulerCronJobs:
    def test_add_and_get_cron_jobs(self):
        scheduler = Scheduler()
        job = CronJob(id="j1", name="Test Job", schedule="0 9 * * *", task="hello")
        scheduler.add_cron_job(job)

        jobs = scheduler.get_cron_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "j1"
        assert jobs[0]["name"] == "Test Job"
        assert jobs[0]["schedule"] == "0 9 * * *"
        assert jobs[0]["task"] == "hello"
        assert jobs[0]["enabled"] is True
        # next_run should be set by add_cron_job
        assert jobs[0]["next_run"] is not None

    def test_remove_cron_job(self):
        scheduler = Scheduler()
        job = CronJob(id="j1", name="Test", schedule="0 9 * * *", task="x")
        scheduler.add_cron_job(job)
        assert scheduler.remove_cron_job("j1") is True
        assert scheduler.get_cron_jobs() == []

    def test_remove_nonexistent_cron_job(self):
        scheduler = Scheduler()
        assert scheduler.remove_cron_job("nope") is False

    def test_enable_disable_cron_job(self):
        scheduler = Scheduler()
        job = CronJob(id="j1", name="Test", schedule="0 9 * * *", task="x")
        scheduler.add_cron_job(job)

        scheduler.enable_cron_job("j1", False)
        jobs = scheduler.get_cron_jobs()
        assert jobs[0]["enabled"] is False

        scheduler.enable_cron_job("j1", True)
        jobs = scheduler.get_cron_jobs()
        assert jobs[0]["enabled"] is True

    def test_enable_nonexistent_job(self):
        scheduler = Scheduler()
        # Should not raise
        scheduler.enable_cron_job("nope", True)


class TestSchedulerHeartbeats:
    def test_add_and_get_heartbeats(self):
        scheduler = Scheduler()
        hb = HeartbeatTask(id="h1", name="Check", interval_minutes=10, task="ping")
        scheduler.add_heartbeat(hb)

        heartbeats = scheduler.get_heartbeats()
        assert len(heartbeats) == 1
        assert heartbeats[0]["id"] == "h1"
        assert heartbeats[0]["name"] == "Check"
        assert heartbeats[0]["interval_minutes"] == 10
        assert heartbeats[0]["task"] == "ping"
        assert heartbeats[0]["enabled"] is True

    def test_remove_heartbeat(self):
        scheduler = Scheduler()
        hb = HeartbeatTask(id="h1", name="Check", task="ping")
        scheduler.add_heartbeat(hb)
        assert scheduler.remove_heartbeat("h1") is True
        assert scheduler.get_heartbeats() == []

    def test_remove_nonexistent_heartbeat(self):
        scheduler = Scheduler()
        assert scheduler.remove_heartbeat("nope") is False

    def test_enable_disable_heartbeat(self):
        scheduler = Scheduler()
        hb = HeartbeatTask(id="h1", name="Check", task="ping")
        scheduler.add_heartbeat(hb)

        scheduler.enable_heartbeat("h1", False)
        assert scheduler.get_heartbeats()[0]["enabled"] is False

        scheduler.enable_heartbeat("h1", True)
        assert scheduler.get_heartbeats()[0]["enabled"] is True

    def test_enable_nonexistent_heartbeat(self):
        scheduler = Scheduler()
        # Should not raise
        scheduler.enable_heartbeat("nope", True)


class TestSchedulerStatus:
    def test_initial_status(self):
        scheduler = Scheduler()
        status = scheduler.get_status()
        assert status["running"] is False
        assert status["cron_jobs"] == 0
        assert status["heartbeats"] == 0
        assert status["total_runs"] == 0

    def test_status_with_jobs(self):
        scheduler = Scheduler()
        scheduler.add_cron_job(CronJob(id="j1", name="A", schedule="0 9 * * *", task="x"))
        scheduler.add_heartbeat(HeartbeatTask(id="h1", name="B", task="y"))
        status = scheduler.get_status()
        assert status["cron_jobs"] == 1
        assert status["heartbeats"] == 1
        assert status["total_runs"] == 0

    def test_status_tracks_run_count(self):
        scheduler = Scheduler()
        job = CronJob(id="j1", name="A", schedule="0 9 * * *", task="x", run_count=5)
        hb = HeartbeatTask(id="h1", name="B", task="y", run_count=3)
        scheduler.add_cron_job(job)
        scheduler.add_heartbeat(hb)
        assert scheduler.get_status()["total_runs"] == 8


class TestSchedulerExecution:
    @pytest.mark.asyncio
    async def test_execute_job_with_async_handler(self):
        handler = AsyncMock()
        scheduler = Scheduler(message_handler=handler)
        job = CronJob(id="j1", name="Test", schedule="0 9 * * *", task="do something")

        await scheduler._execute_job(job)
        handler.assert_awaited_once_with("do something", user="scheduler", channel="cron")

    @pytest.mark.asyncio
    async def test_execute_job_with_sync_handler(self):
        handler = MagicMock()
        scheduler = Scheduler(message_handler=handler)
        job = CronJob(id="j1", name="Test", schedule="0 9 * * *", task="do something")

        await scheduler._execute_job(job)
        handler.assert_called_once_with("do something", user="scheduler", channel="cron")

    @pytest.mark.asyncio
    async def test_execute_job_no_handler(self):
        scheduler = Scheduler()
        job = CronJob(id="j1", name="Test", schedule="0 9 * * *", task="do something")
        # Should not raise
        await scheduler._execute_job(job)

    @pytest.mark.asyncio
    async def test_execute_heartbeat_with_async_handler(self):
        handler = AsyncMock()
        scheduler = Scheduler(message_handler=handler)
        hb = HeartbeatTask(id="h1", name="Check", task="ping services")

        await scheduler._execute_heartbeat(hb)
        handler.assert_awaited_once_with("ping services", user="scheduler", channel="heartbeat")

    @pytest.mark.asyncio
    async def test_execute_heartbeat_with_sync_handler(self):
        handler = MagicMock()
        scheduler = Scheduler(message_handler=handler)
        hb = HeartbeatTask(id="h1", name="Check", task="ping services")

        await scheduler._execute_heartbeat(hb)
        handler.assert_called_once_with("ping services", user="scheduler", channel="heartbeat")

    @pytest.mark.asyncio
    async def test_execute_job_handler_exception(self):
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        scheduler = Scheduler(message_handler=handler)
        job = CronJob(id="j1", name="Test", schedule="0 9 * * *", task="fail")
        # Should not raise, just log
        await scheduler._execute_job(job)

    @pytest.mark.asyncio
    async def test_execute_heartbeat_handler_exception(self):
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        scheduler = Scheduler(message_handler=handler)
        hb = HeartbeatTask(id="h1", name="Check", task="fail")
        # Should not raise, just log
        await scheduler._execute_heartbeat(hb)


class TestCalcNextRun:
    def test_valid_schedule(self):
        scheduler = Scheduler()
        result = scheduler._calc_next_run("30 14 * * *")
        assert result is not None
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result > datetime.now(timezone.utc)

    def test_all_stars(self):
        scheduler = Scheduler()
        result = scheduler._calc_next_run("* * * * *")
        # With all stars, uses current time which is <= now, so adds a day
        assert result is not None
        assert result > datetime.now(timezone.utc)

    def test_invalid_schedule_wrong_parts(self):
        scheduler = Scheduler()
        assert scheduler._calc_next_run("0 9 *") is None

    def test_invalid_schedule_bad_values(self):
        scheduler = Scheduler()
        assert scheduler._calc_next_run("abc def * * *") is None

    def test_empty_schedule(self):
        scheduler = Scheduler()
        assert scheduler._calc_next_run("") is None

    def test_next_run_is_future(self):
        scheduler = Scheduler()
        result = scheduler._calc_next_run("0 9 * * *")
        assert result is not None
        assert result > datetime.now(timezone.utc)


class TestSchedulerStartStop:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        scheduler = Scheduler()
        await scheduler.start()
        assert scheduler._running is True
        assert len(scheduler._tasks) == 2

        await scheduler.stop()
        assert scheduler._running is False
        assert len(scheduler._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        scheduler = Scheduler()
        await scheduler.start()
        await scheduler.start()  # Should not create extra tasks
        assert len(scheduler._tasks) == 2
        await scheduler.stop()


# --- Web API endpoint tests ---


@pytest.fixture
def scheduler():
    return Scheduler()


@pytest.fixture
def web_app_with_scheduler(scheduler):
    app = WebApp(
        message_handler=AsyncMock(return_value="ok"),
        scheduler=scheduler,
    )
    return app


@pytest.fixture
def client_with_scheduler(web_app_with_scheduler):
    return TestClient(web_app_with_scheduler.app)


@pytest.fixture
def client_no_scheduler():
    app = WebApp(message_handler=AsyncMock(return_value="ok"))
    return TestClient(app.app)


class TestSchedulerWebEndpoints:
    def test_scheduler_status(self, client_with_scheduler):
        resp = client_with_scheduler.get("/api/scheduler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"]["running"] is False
        assert data["status"]["cron_jobs"] == 0

    def test_scheduler_status_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.get("/api/scheduler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"]["running"] is False

    def test_list_cron_jobs_empty(self, client_with_scheduler):
        resp = client_with_scheduler.get("/api/scheduler/cron")
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_list_cron_jobs_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.get("/api/scheduler/cron")
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []

    def test_add_cron_job(self, client_with_scheduler):
        resp = client_with_scheduler.post("/api/scheduler/cron", json={
            "id": "test1",
            "name": "Test Job",
            "schedule": "0 9 * * *",
            "task": "hello world",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["job"]["id"] == "test1"
        assert data["job"]["name"] == "Test Job"

        # Verify it's listed
        resp = client_with_scheduler.get("/api/scheduler/cron")
        jobs = resp.json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["id"] == "test1"

    def test_add_cron_job_auto_id(self, client_with_scheduler):
        resp = client_with_scheduler.post("/api/scheduler/cron", json={
            "name": "Auto ID Job",
            "schedule": "0 12 * * *",
            "task": "noon task",
        })
        assert resp.status_code == 200
        assert resp.json()["job"]["id"]  # Should have auto-generated id

    def test_add_cron_job_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.post("/api/scheduler/cron", json={
            "name": "Test", "schedule": "0 9 * * *", "task": "x",
        })
        assert resp.status_code == 503

    def test_delete_cron_job(self, client_with_scheduler):
        client_with_scheduler.post("/api/scheduler/cron", json={
            "id": "del1", "name": "Delete Me", "schedule": "0 9 * * *", "task": "x",
        })
        resp = client_with_scheduler.delete("/api/scheduler/cron/del1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it's gone
        resp = client_with_scheduler.get("/api/scheduler/cron")
        assert resp.json()["jobs"] == []

    def test_delete_nonexistent_cron_job(self, client_with_scheduler):
        resp = client_with_scheduler.delete("/api/scheduler/cron/nope")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"

    def test_delete_cron_job_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.delete("/api/scheduler/cron/x")
        assert resp.status_code == 503

    def test_list_heartbeats_empty(self, client_with_scheduler):
        resp = client_with_scheduler.get("/api/scheduler/heartbeat")
        assert resp.status_code == 200
        assert resp.json()["heartbeats"] == []

    def test_list_heartbeats_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.get("/api/scheduler/heartbeat")
        assert resp.status_code == 200
        assert resp.json()["heartbeats"] == []

    def test_add_heartbeat(self, client_with_scheduler):
        resp = client_with_scheduler.post("/api/scheduler/heartbeat", json={
            "id": "hb1",
            "name": "Health Check",
            "interval_minutes": 15,
            "task": "check services",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["heartbeat"]["id"] == "hb1"

        # Verify it's listed
        resp = client_with_scheduler.get("/api/scheduler/heartbeat")
        hbs = resp.json()["heartbeats"]
        assert len(hbs) == 1
        assert hbs[0]["id"] == "hb1"
        assert hbs[0]["interval_minutes"] == 15

    def test_add_heartbeat_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.post("/api/scheduler/heartbeat", json={
            "name": "Test", "task": "x",
        })
        assert resp.status_code == 503

    def test_delete_heartbeat(self, client_with_scheduler):
        client_with_scheduler.post("/api/scheduler/heartbeat", json={
            "id": "hbdel", "name": "Delete Me", "task": "x",
        })
        resp = client_with_scheduler.delete("/api/scheduler/heartbeat/hbdel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = client_with_scheduler.get("/api/scheduler/heartbeat")
        assert resp.json()["heartbeats"] == []

    def test_delete_nonexistent_heartbeat(self, client_with_scheduler):
        resp = client_with_scheduler.delete("/api/scheduler/heartbeat/nope")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"

    def test_delete_heartbeat_no_scheduler(self, client_no_scheduler):
        resp = client_no_scheduler.delete("/api/scheduler/heartbeat/x")
        assert resp.status_code == 503
