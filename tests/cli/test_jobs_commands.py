# tests/cli/test_jobs_commands.py
import json
import pytest
from breadmind.cli.jobs import cmd_list, cmd_show


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
