"""CodingJobExecutor.execute_plan must propagate user/channel to JobTracker."""
from __future__ import annotations

import pytest

from breadmind.coding.job_executor import CodingJobExecutor
from breadmind.coding.job_tracker import JobTracker


@pytest.fixture(autouse=True)
def _reset_tracker_singleton():
    """Each test starts with a fresh tracker singleton."""
    from breadmind.coding import job_tracker as jt
    jt.JobTracker._instance = None
    yield
    jt.JobTracker._instance = None


async def test_execute_plan_propagates_user_channel(monkeypatch) -> None:
    captured: dict = {}

    real_create_job = JobTracker.create_job
    def _spy(self, job_id, project, agent, prompt, user="", channel=""):
        captured["user"] = user
        captured["channel"] = channel
        return real_create_job(self, job_id, project, agent, prompt, user, channel)

    monkeypatch.setattr(JobTracker, "create_job", _spy)

    # Provide a plan with zero phases so execute_plan returns immediately
    # — but only AFTER it called create_job. Test pivot.
    executor = CodingJobExecutor(provider=None, db=None)
    await executor.execute_plan(
        plan_data={"project": "p", "agent": "claude", "phases": [], "original_prompt": "hi"},
        job_id="j1",
        user="alice",
        channel="#dev",
    )

    # NOTE: with phases=[] the current code returns BEFORE create_job.
    # The implementation must be moved so create_job is called regardless.
    assert captured.get("user") == "alice"
    assert captured.get("channel") == "#dev"
