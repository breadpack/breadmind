# tests/cli/test_jobs_commands.py
import json
import pytest
from breadmind.cli.jobs import cmd_cancel, cmd_list, cmd_logs, cmd_show


class FakeClient:
    def __init__(self, jobs=None, job=None):
        self._jobs = jobs or []
        self._job = job
    async def list_jobs(self, *, mine, status, limit):
        return list(self._jobs)
    async def get_job(self, job_id):
        return self._job


@pytest.mark.asyncio
async def test_cmd_list_table(capsys):
    client = FakeClient(jobs=[
        {"job_id": "a", "status": "running", "project": "p", "prompt": "xx",
         "user": "alice", "progress_pct": 50, "total_phases": 2,
         "completed_phases": 1, "started_at": 0},
    ])
    rc = await cmd_list(client, mine=True, status=None, limit=50, fmt="table")
    out = capsys.readouterr().out
    assert "a" in out and "alice" in out and "50%" in out
    assert rc == 0


@pytest.mark.asyncio
async def test_cmd_list_json(capsys):
    client = FakeClient(jobs=[{"job_id": "a", "status": "done"}])
    await cmd_list(client, mine=False, status=None, limit=10, fmt="json")
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["job_id"] == "a"


@pytest.mark.asyncio
async def test_cmd_show_not_found(capsys):
    client = FakeClient(job=None)
    rc = await cmd_show(client, "missing", fmt="table")
    out = capsys.readouterr().out
    assert "not found" in out.lower() or "404" in out
    assert rc != 0


@pytest.mark.asyncio
async def test_cmd_cancel_ok(capsys):
    class C(FakeClient):
        async def cancel_job(self, job_id):
            return 200
    rc = await cmd_cancel(C(), "j1")
    assert rc == 0


@pytest.mark.asyncio
async def test_cmd_cancel_forbidden(capsys):
    class C(FakeClient):
        async def cancel_job(self, job_id):
            return 403
    rc = await cmd_cancel(C(), "j1")
    out = capsys.readouterr().out + capsys.readouterr().err
    assert rc == 3


@pytest.mark.asyncio
async def test_cmd_logs_one_shot(capsys):
    class C(FakeClient):
        async def list_logs(self, job_id, step, *, after, limit):
            return {"items": [
                {"line_no": 1, "ts": "2026-04-23T00:00:00Z", "text": "hello"},
                {"line_no": 2, "ts": "2026-04-23T00:00:01Z", "text": "world"},
            ], "next_after_line_no": 2}
    rc = await cmd_logs(C(), "j1", phase=1, follow=False, lines=100, plain=True)
    out = capsys.readouterr().out
    assert "hello" in out and "world" in out
    assert rc == 0
