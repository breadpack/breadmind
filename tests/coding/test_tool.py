"""code_delegate(user, channel) propagation tests."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from breadmind.coding.tool import (
    _execute_long_running,
    _run_long_running_background,
    create_code_delegate_tool,
)


async def test_code_delegate_long_running_forwards_user_channel(monkeypatch) -> None:
    """user/channel must reach _execute_long_running."""
    captured: dict = {}

    async def fake_execute_long_running(**kw):
        captured.update(kw)
        from breadmind.tools.registry import ToolResult
        return ToolResult(success=True, output="job started")

    monkeypatch.setattr(
        "breadmind.coding.tool._execute_long_running",
        fake_execute_long_running,
    )
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )
    res = await code_delegate(
        agent="claude", project="/tmp/p", prompt="hi",
        long_running=True, user="alice", channel="#dev",
    )
    assert res.success
    assert captured["user"] == "alice"
    assert captured["channel"] == "#dev"


async def test_code_delegate_default_user_channel_empty(monkeypatch) -> None:
    """Defaults are empty strings; backwards compat."""
    captured: dict = {}

    async def fake_execute_long_running(**kw):
        captured.update(kw)
        from breadmind.tools.registry import ToolResult
        return ToolResult(success=True, output="ok")

    monkeypatch.setattr(
        "breadmind.coding.tool._execute_long_running",
        fake_execute_long_running,
    )
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )
    await code_delegate(
        agent="claude", project="/tmp/p", prompt="hi", long_running=True,
    )
    assert captured["user"] == ""
    assert captured["channel"] == ""


def test_register_job_for_delegation_removed() -> None:
    """Dead helper from pre-Task-9 wiring must be gone."""
    from breadmind.coding import tool
    assert not hasattr(tool, "_register_job_for_delegation")


# Silence unused-import warning for asyncio; kept available for potential
# future spawn/cancel tests.
_ = asyncio


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_tracker_singleton():
    """Each test starts with a fresh tracker singleton so state doesn't leak."""
    from breadmind.coding import job_tracker as jt
    jt.JobTracker._instance = None
    yield
    jt.JobTracker._instance = None


# ── _execute_long_running direct unit tests ────────────────────────────────


async def test_execute_long_running_returns_job_id_and_schedules_bg(
    tmp_path, monkeypatch,
) -> None:
    """_execute_long_running returns ToolResult with job_id and schedules bg task."""
    captured: dict = {}

    async def fake_bg(**kw):  # pragma: no cover - only awaited
        captured.update(kw)

    monkeypatch.setattr(
        "breadmind.coding.tool._run_long_running_background", fake_bg,
    )

    res = await _execute_long_running(
        agent="claude",
        project=str(tmp_path),
        prompt="hi",
        model="",
        timeout=10,
        provider=object(),
        db=None,
        user="u1",
        channel="c1",
    )

    assert res.success is True
    assert "Job ID" in res.output
    assert "[claude]" in res.output

    # Give the event loop a tick to run the scheduled task.
    await asyncio.sleep(0)
    assert captured.get("user") == "u1"
    assert captured.get("channel") == "c1"
    assert captured.get("agent") == "claude"
    assert captured.get("prompt") == "hi"


async def test_execute_long_running_creates_project_dir_if_missing(
    tmp_path, monkeypatch,
) -> None:
    """_execute_long_running ensures the project path exists."""
    async def fake_bg(**kw):  # pragma: no cover - not awaited for assertions
        return None

    monkeypatch.setattr(
        "breadmind.coding.tool._run_long_running_background", fake_bg,
    )

    target = tmp_path / "nested" / "project"
    assert not target.exists()

    res = await _execute_long_running(
        agent="claude",
        project=str(target),
        prompt="p",
        model="",
        timeout=10,
        provider=object(),
        db=None,
    )

    assert res.success is True
    assert target.is_dir()


# ── _run_long_running_background paths ────────────────────────────────────


async def test_run_long_running_background_empty_phases_records_failure(
    monkeypatch,
) -> None:
    """When the decomposer returns no phases, tracker records a failed job."""
    fake_plan = SimpleNamespace(phases=[])

    class FakeDecomposer:
        def __init__(self, provider):
            self.provider = provider

        async def decompose(self, project, prompt, agent, model):
            return fake_plan

    monkeypatch.setattr(
        "breadmind.coding.task_decomposer.TaskDecomposer", FakeDecomposer,
    )

    await _run_long_running_background(
        job_id="jEmpty",
        agent="claude",
        project="/tmp/p",
        prompt="go",
        model="",
        provider=object(),
        db=None,
        user="alice",
        channel="#dev",
    )

    from breadmind.coding.job_tracker import JobTracker
    tracker = JobTracker.get_instance()
    job = tracker.get_job("jEmpty")
    assert job is not None
    assert job.status.value == "failed"
    assert job.user == "alice"
    assert job.channel == "#dev"
    assert "no phases" in (job.error or "").lower()


async def test_run_long_running_background_executor_path(monkeypatch) -> None:
    """With phases, the executor.execute_plan is invoked with user/channel."""
    captured: dict = {}

    fake_phase = SimpleNamespace(
        step=1, title="t1", prompt="p1", timeout=60,
    )
    fake_plan = SimpleNamespace(phases=[fake_phase])

    class FakeDecomposer:
        def __init__(self, provider):
            pass

        async def decompose(self, project, prompt, agent, model):
            return fake_plan

    monkeypatch.setattr(
        "breadmind.coding.task_decomposer.TaskDecomposer", FakeDecomposer,
    )

    class FakeExecutor:
        def __init__(self, provider=None, db=None):
            self.provider = provider
            self.db = db

        async def execute_plan(self, plan_data, **kw):
            captured["plan_data"] = plan_data
            captured.update(kw)
            return {"success": True}

    monkeypatch.setattr(
        "breadmind.coding.job_executor.CodingJobExecutor", FakeExecutor,
    )

    await _run_long_running_background(
        job_id="jExec",
        agent="claude",
        project="/tmp/p",
        prompt="build",
        model="gpt",
        provider=object(),
        db=None,
        user="bob",
        channel="#ops",
    )

    assert captured.get("user") == "bob"
    assert captured.get("channel") == "#ops"
    assert captured.get("job_id") == "jExec"
    plan_data = captured.get("plan_data")
    assert plan_data["project"] == "/tmp/p"
    assert plan_data["agent"] == "claude"
    assert plan_data["model"] == "gpt"
    assert plan_data["original_prompt"] == "build"
    assert len(plan_data["phases"]) == 1
    assert plan_data["phases"][0]["step"] == 1
    assert plan_data["phases"][0]["title"] == "t1"


async def test_run_long_running_background_decompose_exception(monkeypatch) -> None:
    """When decompose raises, tracker records a failed job with error."""
    class FakeDecomposer:
        def __init__(self, provider):
            pass

        async def decompose(self, project, prompt, agent, model):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "breadmind.coding.task_decomposer.TaskDecomposer", FakeDecomposer,
    )

    await _run_long_running_background(
        job_id="jErr",
        agent="claude",
        project="/tmp/p",
        prompt="x",
        model="",
        provider=object(),
        db=None,
        user="carol",
        channel="#bug",
    )

    from breadmind.coding.job_tracker import JobTracker
    tracker = JobTracker.get_instance()
    job = tracker.get_job("jErr")
    assert job is not None
    assert job.status.value == "failed"
    assert "boom" in (job.error or "")
    assert job.user == "carol"
    assert job.channel == "#bug"


async def test_run_long_running_background_exception_after_job_exists(
    monkeypatch,
) -> None:
    """When executor raises after create_job happened, tracker finalizes the job."""
    fake_phase = SimpleNamespace(step=1, title="t", prompt="p", timeout=30)
    fake_plan = SimpleNamespace(phases=[fake_phase])

    class FakeDecomposer:
        def __init__(self, provider):
            pass

        async def decompose(self, project, prompt, agent, model):
            return fake_plan

    monkeypatch.setattr(
        "breadmind.coding.task_decomposer.TaskDecomposer", FakeDecomposer,
    )

    class FakeExecutor:
        def __init__(self, provider=None, db=None):
            pass

        async def execute_plan(self, plan_data, **kw):
            # Register the job first so the `if not tracker.get_job(...)`
            # branch on line 405 is exercised (job already exists path).
            from breadmind.coding.job_tracker import JobTracker
            tracker = JobTracker.get_instance()
            tracker.create_job(
                kw["job_id"], plan_data["project"], plan_data["agent"],
                plan_data["original_prompt"],
                user=kw.get("user", ""), channel=kw.get("channel", ""),
            )
            raise RuntimeError("late failure")

    monkeypatch.setattr(
        "breadmind.coding.job_executor.CodingJobExecutor", FakeExecutor,
    )

    await _run_long_running_background(
        job_id="jLate",
        agent="claude",
        project="/tmp/p",
        prompt="x",
        model="",
        provider=object(),
        db=None,
        user="dave",
        channel="#late",
    )

    from breadmind.coding.job_tracker import JobTracker
    tracker = JobTracker.get_instance()
    job = tracker.get_job("jLate")
    assert job is not None
    assert job.status.value == "failed"
    assert "late failure" in (job.error or "")


# ── code_delegate non-long_running paths ──────────────────────────────────


async def test_code_delegate_unknown_agent_returns_error() -> None:
    """get_adapter raises ValueError for unknown agents; tool surfaces it."""
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=None,
    )
    res = await code_delegate(
        agent="unknown-agent-xyz",
        project="/tmp/p",
        prompt="hi",
        long_running=False,
    )
    assert res.success is False
    assert "Unknown coding agent" in res.output


async def test_code_delegate_missing_project_directory(tmp_path) -> None:
    """Missing project dir triggers the `Project directory not found` branch."""
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=None,
    )
    bogus = tmp_path / "does-not-exist"
    res = await code_delegate(
        agent="claude",
        project=str(bogus),
        prompt="hi",
        long_running=False,
    )
    assert res.success is False
    assert "Project directory not found" in res.output


async def test_code_delegate_local_execute_success_path(
    tmp_path, monkeypatch,
) -> None:
    """Exercises the non-long_running local-execute path with channel disabled.

    Covers options/session_id/model branches + executor selection + parse_result
    and result formatting. Channel supervision is neutralised by monkeypatching
    _channel_available to False.
    """
    monkeypatch.setattr(
        "breadmind.coding.tool._channel_available", lambda: False,
    )

    fake_adapter = SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", "hi"],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=True,
            output="done",
            files_changed=["a.py"],
            session_id="sess-42",
            execution_time=0.0,
            agent="",
        ),
    )
    monkeypatch.setattr(
        "breadmind.coding.tool.get_adapter", lambda name: fake_adapter,
    )

    class FakeExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="out", stderr="", returncode=0)

    monkeypatch.setattr(
        "breadmind.coding.tool.LocalExecutor", lambda: FakeExec(),
    )

    session_store = AsyncMock()
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=session_store, provider=None,
    )

    res = await code_delegate(
        agent="claude",
        project=str(tmp_path),
        prompt="do the thing",
        model="opus-4",
        session_id="sess-prev",
        long_running=False,
    )

    assert res.success is True
    # Session store was awaited because the adapter reports a session_id
    session_store.save_session.assert_awaited()
    assert "Session: sess-42" in res.output
    assert "Files changed: a.py" in res.output


async def test_code_delegate_channel_supervised_new_mcp_json(
    tmp_path, monkeypatch,
) -> None:
    """Channel-supervised branch: no .mcp.json at start; it gets written & removed."""
    monkeypatch.setattr(
        "breadmind.coding.tool._channel_available", lambda: True,
    )

    fake_adapter = SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", "hi"],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=True,
            output="done",
            files_changed=[],
            session_id="",
            execution_time=0.0,
            agent="",
        ),
    )
    monkeypatch.setattr(
        "breadmind.coding.tool.get_adapter", lambda name: fake_adapter,
    )

    class FakeExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="out", stderr="", returncode=0)

    monkeypatch.setattr(
        "breadmind.coding.tool.LocalExecutor", lambda: FakeExec(),
    )

    class FakeSupervisor:
        def __init__(self, provider=None, max_auto_retries=3):
            self.provider = provider

        async def start(self, session_id, project, prompt):
            return (9001, 9002)

        def get_mcp_config_entry(self):
            return {"command": "bun", "args": ["run", "channel-server"]}

        async def stop(self):
            return SimpleNamespace(summary="sup-report")

    monkeypatch.setattr(
        "breadmind.coding.channel_supervisor.ChannelSupervisor", FakeSupervisor,
    )

    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )

    res = await code_delegate(
        agent="claude",
        project=str(tmp_path),
        prompt="hi",
        long_running=False,
    )

    assert res.success is True
    # Supervisor report was substituted into the output
    assert "sup-report" in res.output
    # .mcp.json was cleaned up post-run
    assert not (tmp_path / ".mcp.json").exists()


async def test_code_delegate_channel_supervised_preexisting_mcp_json(
    tmp_path, monkeypatch,
) -> None:
    """Channel-supervised branch with preexisting .mcp.json: backup+restore."""
    original = {"mcpServers": {"existing": {"command": "nope"}}}
    mcp_path = tmp_path / ".mcp.json"
    import json as _json
    mcp_path.write_text(_json.dumps(original), encoding="utf-8")

    monkeypatch.setattr(
        "breadmind.coding.tool._channel_available", lambda: True,
    )
    fake_adapter = SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", "hi"],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=True, output="done", files_changed=[],
            session_id="", execution_time=0.0, agent="",
        ),
    )
    monkeypatch.setattr(
        "breadmind.coding.tool.get_adapter", lambda name: fake_adapter,
    )

    class FakeExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(
        "breadmind.coding.tool.LocalExecutor", lambda: FakeExec(),
    )

    class FakeSupervisor:
        def __init__(self, **kw):
            pass

        async def start(self, **kw):
            return (1234, 5678)

        def get_mcp_config_entry(self):
            return {"command": "bun"}

        async def stop(self):
            # Trigger the except branch for supervisor.stop() failure
            raise RuntimeError("cannot stop")

    monkeypatch.setattr(
        "breadmind.coding.channel_supervisor.ChannelSupervisor", FakeSupervisor,
    )

    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )

    res = await code_delegate(
        agent="claude", project=str(tmp_path), prompt="p", long_running=False,
    )

    assert res.success is True
    # File restored to original contents
    assert mcp_path.exists()
    restored = _json.loads(mcp_path.read_text(encoding="utf-8"))
    assert restored == original


async def test_code_delegate_channel_setup_exception(
    tmp_path, monkeypatch,
) -> None:
    """ChannelSupervisor raising during start is absorbed; execution continues."""
    monkeypatch.setattr(
        "breadmind.coding.tool._channel_available", lambda: True,
    )
    fake_adapter = SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", "hi"],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=True, output="done", files_changed=[],
            session_id="", execution_time=0.0, agent="",
        ),
    )
    monkeypatch.setattr(
        "breadmind.coding.tool.get_adapter", lambda name: fake_adapter,
    )

    class FakeExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(
        "breadmind.coding.tool.LocalExecutor", lambda: FakeExec(),
    )

    class BrokenSupervisor:
        def __init__(self, **kw):
            raise RuntimeError("setup failed")

    monkeypatch.setattr(
        "breadmind.coding.channel_supervisor.ChannelSupervisor", BrokenSupervisor,
    )

    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )

    res = await code_delegate(
        agent="claude", project=str(tmp_path), prompt="p", long_running=False,
    )
    assert res.success is True


async def test_code_delegate_local_execute_failure_path(
    tmp_path, monkeypatch,
) -> None:
    """Failure branch: non-zero returncode flows into formatted output."""
    monkeypatch.setattr(
        "breadmind.coding.tool._channel_available", lambda: False,
    )

    fake_adapter = SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", "hi"],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=False,
            output="boom",
            files_changed=[],
            session_id="",
            execution_time=0.0,
            agent="",
        ),
    )
    monkeypatch.setattr(
        "breadmind.coding.tool.get_adapter", lambda name: fake_adapter,
    )

    class FakeExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="", stderr="err", returncode=2)

    monkeypatch.setattr(
        "breadmind.coding.tool.LocalExecutor", lambda: FakeExec(),
    )

    session_store = AsyncMock()
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=session_store, provider=None,
    )

    res = await code_delegate(
        agent="claude",
        project=str(tmp_path),
        prompt="p",
        long_running=False,
    )

    assert res.success is False
    assert "exit code: 2" in res.output
    # No session id — save_session not called
    session_store.save_session.assert_not_awaited()
