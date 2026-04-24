"""CodingJobExecutor.execute_plan must propagate user/channel to JobTracker."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from breadmind.coding.job_executor import (
    CodingJobExecutor,
    _capture_stream_to_tracker,
)
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


# ── _capture_stream_to_tracker unit tests ──────────────────────────────────


class _FakeStream:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeTracker:
    def __init__(self, raise_on_append: bool = False):
        self.calls: list[tuple] = []
        self._raise = raise_on_append

    async def append_log(self, job_id, step, line):
        self.calls.append((job_id, step, line))
        if self._raise:
            raise RuntimeError("tracker boom")


async def test_capture_stream_appends_redacted_lines() -> None:
    """Happy path: readline yields two lines, both pushed to tracker."""
    stream = _FakeStream([b"hello\n", b"world\r\n"])
    tracker = _FakeTracker()
    await _capture_stream_to_tracker(
        stream, tracker, job_id="j1", step=1,
    )
    assert len(tracker.calls) == 2
    assert tracker.calls[0] == ("j1", 1, "hello")
    assert tracker.calls[1] == ("j1", 1, "world")


async def test_capture_stream_redact_failure_is_absorbed(monkeypatch) -> None:
    """When redact_secrets raises, line is dropped and metric incremented."""
    def _boom(_line):
        raise RuntimeError("redact failed")
    monkeypatch.setattr(
        "breadmind.coding.job_executor.redact_secrets", _boom,
    )

    stream = _FakeStream([b"leak\n"])
    tracker = _FakeTracker()
    await _capture_stream_to_tracker(
        stream, tracker, job_id="j2", step=3,
    )
    # No append was made — the line was dropped.
    assert tracker.calls == []


async def test_capture_stream_tracker_append_failure_is_absorbed() -> None:
    """Tracker.append_log raising must not propagate out of the capture loop."""
    stream = _FakeStream([b"oops\n", b"ok\n"])
    tracker = _FakeTracker(raise_on_append=True)
    # Must complete normally despite tracker exceptions.
    await _capture_stream_to_tracker(
        stream, tracker, job_id="j3", step=2,
    )
    # Both lines were attempted.
    assert len(tracker.calls) == 2


# ── execute_plan phased-run tests ──────────────────────────────────────────


def _make_adapter(*, session_id: str = "sess-1", success: bool = True):
    return SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", prompt],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=success,
            output="phase-output",
            files_changed=["x.py"],
            session_id=session_id,
            execution_time=0.0,
            agent="",
        ),
    )


def _patch_shared_executor_deps(monkeypatch, adapter, exec_cls,
                                 supervisor_cls):
    monkeypatch.setattr(
        "breadmind.coding.adapters.get_adapter", lambda name: adapter,
    )
    monkeypatch.setattr(
        "breadmind.coding.executors.local.LocalExecutor", exec_cls,
    )
    monkeypatch.setattr(
        "breadmind.coding.channel_supervisor.ChannelSupervisor", supervisor_cls,
    )


async def test_execute_plan_two_phases_all_success(tmp_path, monkeypatch) -> None:
    """Full phased run: adapter + local executor + supervisor mocked."""
    adapter = _make_adapter(session_id="sess-new")

    class FakeLocalExec:
        def __init__(self):
            self.calls = 0

        async def run(self, command, cwd, timeout):
            self.calls += 1
            return SimpleNamespace(stdout="out", stderr="", returncode=0)

    class FakeSupervisor:
        def __init__(self, provider=None, max_auto_retries=3):
            self.provider = provider

        async def start(self, session_id, project, prompt):
            return (1111, 2222)

        def get_mcp_config_entry(self):
            return {"command": "bun"}

        async def stop(self):
            return SimpleNamespace(summary="phase-report")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: FakeLocalExec(), FakeSupervisor,
    )

    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "model": "opus",
        "original_prompt": "orig",
        "phases": [
            {"step": 1, "title": "p1", "prompt": "do 1", "timeout": 30},
            {"step": 2, "title": "p2", "prompt": "do 2", "timeout": 30},
        ],
    }

    notify = AsyncMock()
    executor = CodingJobExecutor(provider=object(), db=None,
                                 notify_callback=notify)
    store = SimpleNamespace(
        update_progress=AsyncMock(),
        update_status=AsyncMock(),
    )
    pub_events: list[tuple] = []

    def publish(job_id, event):
        pub_events.append((job_id, event))

    summary = await executor.execute_plan(
        plan_data=plan,
        job_id="jFull",
        store=store,
        publish_fn=publish,
        user="e-u", channel="e-c",
    )

    assert summary["success"] is True
    assert summary["phases_completed"] == "2/2"
    assert len(summary["results"]) == 2
    # Progress/status/completion written to store
    store.update_status.assert_awaited()
    # Publish stream included "completed" at the end
    assert any(evt.get("type") == "completed" for _, evt in pub_events)
    # JobTracker has the job as completed with user/channel
    from breadmind.coding.job_tracker import JobTracker
    job = JobTracker.get_instance().get_job("jFull")
    assert job is not None
    assert job.user == "e-u"
    assert job.channel == "e-c"
    assert job.status.value == "completed"
    # .mcp.json was cleaned up
    assert not (tmp_path / ".mcp.json").exists()


async def test_execute_plan_unknown_agent_returns_error() -> None:
    """When get_adapter raises ValueError, execute_plan returns failure dict."""
    executor = CodingJobExecutor(provider=None, db=None)
    res = await executor.execute_plan(
        plan_data={
            "project": "/tmp/x",
            "agent": "does-not-exist",
            "phases": [
                {"step": 1, "title": "t", "prompt": "p", "timeout": 10},
            ],
            "original_prompt": "hi",
        },
        job_id="jBad",
    )
    assert res["success"] is False
    assert "Unknown coding agent" in res["error"]


async def test_execute_plan_empty_phases_marks_failed() -> None:
    """Empty phases are registered then immediately marked failed."""
    executor = CodingJobExecutor(provider=None, db=None)
    res = await executor.execute_plan(
        plan_data={
            "project": "/tmp/e",
            "agent": "claude",
            "phases": [],
            "original_prompt": "x",
        },
        job_id="jEmpty2",
    )
    assert res["success"] is False
    assert "No phases" in res["error"]
    from breadmind.coding.job_tracker import JobTracker
    job = JobTracker.get_instance().get_job("jEmpty2")
    assert job is not None
    assert job.status.value == "failed"


async def test_execute_plan_phase_exception_captured(tmp_path, monkeypatch) -> None:
    """Executor.run raising is captured as a failed phase result."""
    adapter = _make_adapter()

    class ExplodingExec:
        async def run(self, command, cwd, timeout):
            raise RuntimeError("kaboom")

    class SupOk:
        def __init__(self, **kw):
            pass

        async def start(self, **kw):
            return (7000, 7001)

        def get_mcp_config_entry(self):
            return {"command": "bun"}

        async def stop(self):
            return SimpleNamespace(summary="")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: ExplodingExec(), SupOk,
    )

    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "original_prompt": "o",
        "phases": [
            {"step": 1, "title": "one", "prompt": "q", "timeout": 10},
        ],
    }
    executor = CodingJobExecutor(provider=object(), db=None)
    summary = await executor.execute_plan(plan, job_id="jExc")

    assert summary["success"] is False
    assert summary["results"][0]["success"] is False
    assert "kaboom" in summary["results"][0]["output"]


async def test_execute_plan_channel_setup_failure(tmp_path, monkeypatch) -> None:
    """Broken ChannelSupervisor is absorbed; phase still runs via legacy path."""
    adapter = _make_adapter(success=True)

    class FakeLocalExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    class BrokenSup:
        def __init__(self, **kw):
            raise RuntimeError("channel setup broke")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: FakeLocalExec(), BrokenSup,
    )

    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "original_prompt": "o",
        "phases": [
            {"step": 1, "title": "one", "prompt": "q", "timeout": 10},
        ],
    }
    executor = CodingJobExecutor(provider=object(), db=None)
    summary = await executor.execute_plan(plan, job_id="jChan")
    assert summary["success"] is True
    # .mcp.json was not created (supervisor failed before writing)
    assert not (tmp_path / ".mcp.json").exists()


async def test_execute_plan_preexisting_mcp_json_restored(
    tmp_path, monkeypatch,
) -> None:
    """Phase that runs with a preexisting .mcp.json restores it after cleanup."""
    import json as _json
    original = {"mcpServers": {"existing": {"command": "nope"}}}
    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(_json.dumps(original), encoding="utf-8")

    adapter = _make_adapter()

    class FakeLocalExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    class SupOk:
        def __init__(self, **kw):
            pass

        async def start(self, **kw):
            return (8000, 8001)

        def get_mcp_config_entry(self):
            return {"command": "bun", "args": ["run"]}

        async def stop(self):
            # Trigger the supervisor.stop() exception branch as a bonus.
            raise RuntimeError("stop exploded")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: FakeLocalExec(), SupOk,
    )

    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "original_prompt": "o",
        "phases": [
            {"step": 1, "title": "one", "prompt": "q", "timeout": 10},
        ],
    }
    executor = CodingJobExecutor(provider=object(), db=None)
    await executor.execute_plan(plan, job_id="jRestore")
    # Restored
    restored = _json.loads(mcp_path.read_text(encoding="utf-8"))
    assert restored == original


async def test_execute_plan_async_streaming_path(tmp_path, monkeypatch) -> None:
    """Executor with run_phase_async is driven through the streaming branch."""
    adapter = _make_adapter()

    class AsyncProc:
        def __init__(self):
            self.stdout = _FakeStream([b"stdout line\n"])
            self.stderr = _FakeStream([b"stderr line\n"])

        async def wait(self):
            return 0

    class AsyncExec:
        async def run_phase_async(self, phase, adapter):
            return AsyncProc()

    class SupOk:
        def __init__(self, **kw):
            pass

        async def start(self, **kw):
            return (1, 2)

        def get_mcp_config_entry(self):
            return {"command": "bun"}

        async def stop(self):
            return SimpleNamespace(summary="ok")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: AsyncExec(), SupOk,
    )

    pub: list = []
    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "original_prompt": "o",
        "phases": [
            {"step": 1, "title": "s", "prompt": "q", "timeout": 10},
        ],
    }
    executor = CodingJobExecutor(provider=object(), db=None)
    summary = await executor.execute_plan(
        plan, job_id="jAsync",
        publish_fn=lambda jid, evt: pub.append(evt),
    )
    assert summary["success"] is True
    assert summary["results"][0]["success"] is True
    # phase_complete published for the async path
    assert any(e.get("type") == "phase_complete" for e in pub)


async def test_execute_plan_async_streaming_nonzero_rc(tmp_path, monkeypatch) -> None:
    """run_phase_async with non-zero return code: failure branch, notify called."""
    adapter = _make_adapter()

    class AsyncProc:
        def __init__(self):
            self.stdout = _FakeStream([])
            self.stderr = _FakeStream([])

        async def wait(self):
            return 5

    class AsyncExec:
        async def run_phase_async(self, phase, adapter):
            return AsyncProc()

    class SupBroken:
        """Stop() raises to exercise the except in the async branch."""
        def __init__(self, **kw):
            pass

        async def start(self, **kw):
            return (1, 2)

        def get_mcp_config_entry(self):
            return {"command": "bun"}

        async def stop(self):
            raise RuntimeError("stop failed")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: AsyncExec(), SupBroken,
    )

    notify = AsyncMock()
    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "original_prompt": "o",
        "phases": [
            {"step": 1, "title": "s", "prompt": "q", "timeout": 10},
        ],
    }
    executor = CodingJobExecutor(
        provider=object(), db=None, notify_callback=notify,
    )
    summary = await executor.execute_plan(plan, job_id="jAsyncFail")
    assert summary["success"] is False
    # notify was called with started, then with failed (rc=5)
    names = [call.args for call in notify.await_args_list]
    assert any("failed" in call for call in names)


async def test_execute_plan_phase_failure_continues(tmp_path, monkeypatch) -> None:
    """A failed parse_result marks that phase failed but continues to next phase."""
    adapter = SimpleNamespace(
        build_command=lambda project, prompt, opts: ["echo", prompt],
        parse_result=lambda stdout, stderr, rc: SimpleNamespace(
            success=False,  # both phases "fail"
            output="oh no",
            files_changed=[],
            session_id="",
            execution_time=0.0,
            agent="",
        ),
    )

    class FakeLocalExec:
        async def run(self, command, cwd, timeout):
            return SimpleNamespace(stdout="", stderr="boom", returncode=3)

    class SupOk:
        def __init__(self, **kw):
            pass

        async def start(self, **kw):
            return (9999, 9998)

        def get_mcp_config_entry(self):
            return {"command": "bun"}

        async def stop(self):
            return SimpleNamespace(summary="")

    _patch_shared_executor_deps(
        monkeypatch, adapter, lambda: FakeLocalExec(), SupOk,
    )

    notify = AsyncMock()
    plan = {
        "project": str(tmp_path),
        "agent": "claude",
        "original_prompt": "o",
        "phases": [
            {"step": 1, "title": "one", "prompt": "q1", "timeout": 10},
            {"step": 2, "title": "two", "prompt": "q2", "timeout": 10},
        ],
    }
    executor = CodingJobExecutor(
        provider=object(), db=None, notify_callback=notify,
    )
    summary = await executor.execute_plan(plan, job_id="jAllFail")

    assert summary["success"] is False
    assert summary["phases_completed"] == "0/2"
    # Both phases ran: notify was called with started + failed for each
    assert notify.await_count >= 4
    from breadmind.coding.job_tracker import JobTracker
    job = JobTracker.get_instance().get_job("jAllFail")
    assert job is not None
    assert job.status.value == "failed"
