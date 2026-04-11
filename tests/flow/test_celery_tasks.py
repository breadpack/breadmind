"""Tests for the Celery step dispatcher."""
from __future__ import annotations

from uuid import uuid4

from breadmind.flow.celery_tasks import CeleryStepDispatcher


class FakeCelery:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def send_task(self, name, args=None, kwargs=None):
        self.calls.append((name, args, kwargs))

        class _R:
            id = "task-1"

        return _R()


async def test_dispatcher_sends_celery_task():
    celery = FakeCelery()
    dispatcher = CeleryStepDispatcher(celery=celery, task_name="flow.execute_step")

    flow_id = uuid4()
    await dispatcher.dispatch(flow_id, "s1", "shell_exec", {"cmd": "echo hi"})
    assert len(celery.calls) == 1
    assert celery.calls[0][0] == "flow.execute_step"
    kwargs = celery.calls[0][2]
    assert kwargs["flow_id"] == str(flow_id)
    assert kwargs["step_id"] == "s1"
    assert kwargs["tool"] == "shell_exec"
    assert kwargs["args"] == {"cmd": "echo hi"}


async def test_dispatcher_handles_none_tool():
    celery = FakeCelery()
    dispatcher = CeleryStepDispatcher(celery=celery, task_name="flow.execute_step")
    flow_id = uuid4()
    await dispatcher.dispatch(flow_id, "s2", None, {})
    assert celery.calls[0][2]["tool"] is None


async def test_dispatcher_defaults_none_args_to_empty_dict():
    celery = FakeCelery()
    dispatcher = CeleryStepDispatcher(celery=celery)
    flow_id = uuid4()
    await dispatcher.dispatch(flow_id, "s3", "noop", None)  # type: ignore[arg-type]
    assert celery.calls[0][2]["args"] == {}
