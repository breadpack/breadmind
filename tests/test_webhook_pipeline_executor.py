import pytest
from unittest.mock import AsyncMock

from breadmind.webhook.models import (
    Pipeline, PipelineAction, PipelineContext,
    ActionType, FailureStrategy, PermissionLevel,
)
from breadmind.webhook.pipeline_executor import PipelineExecutor
from breadmind.webhook.actions.base import ActionResult


@pytest.fixture
def mock_handlers():
    handlers = {}
    for at in ActionType:
        h = AsyncMock()
        h.execute = AsyncMock(return_value=ActionResult(success=True, output="ok"))
        handlers[at] = h
    return handlers

@pytest.fixture
def executor(mock_handlers):
    return PipelineExecutor(action_handlers=mock_handlers)

def _make_ctx() -> PipelineContext:
    return PipelineContext(payload={"action": "test"}, headers={}, endpoint="test-ep")

async def test_execute_simple_pipeline(executor, mock_handlers):
    pipeline = Pipeline(name="simple", actions=[
        PipelineAction(action_type=ActionType.TRANSFORM, config={"expression": "True", "output_variable": "x"}),
        PipelineAction(action_type=ActionType.NOTIFY, config={"channel": "slack", "target": "#test", "message": "hi"}),
    ])
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.ADMIN)
    assert log.success
    assert len(log.action_results) == 2
    assert all(r.success for r in log.action_results)

async def test_stop_on_failure(executor, mock_handlers):
    mock_handlers[ActionType.TRANSFORM].execute = AsyncMock(return_value=ActionResult(success=False, error="bad expression"))
    pipeline = Pipeline(name="stop-test", actions=[
        PipelineAction(action_type=ActionType.TRANSFORM, config={}, on_failure=FailureStrategy.STOP),
        PipelineAction(action_type=ActionType.NOTIFY, config={}),
    ])
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.ADMIN)
    assert not log.success
    assert len(log.action_results) == 1

async def test_continue_on_failure(executor, mock_handlers):
    mock_handlers[ActionType.TRANSFORM].execute = AsyncMock(return_value=ActionResult(success=False, error="bad expression"))
    pipeline = Pipeline(name="continue-test", actions=[
        PipelineAction(action_type=ActionType.TRANSFORM, config={}, on_failure=FailureStrategy.CONTINUE),
        PipelineAction(action_type=ActionType.NOTIFY, config={}),
    ])
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.ADMIN)
    assert log.success
    assert len(log.action_results) == 2

async def test_retry_on_failure(executor, mock_handlers):
    call_count = 0
    async def flaky_execute(action, ctx):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return ActionResult(success=False, error="transient")
        return ActionResult(success=True, output="ok")
    mock_handlers[ActionType.HTTP_REQUEST].execute = flaky_execute
    pipeline = Pipeline(name="retry-test", actions=[
        PipelineAction(action_type=ActionType.HTTP_REQUEST, config={}, on_failure=FailureStrategy.RETRY, max_retries=3),
    ])
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.ADMIN)
    assert log.success
    assert call_count == 3

async def test_permission_denied(executor, mock_handlers):
    pipeline = Pipeline(name="perm-test", actions=[
        PipelineAction(action_type=ActionType.CALL_TOOL, config={"tool_name": "shell_execute", "arguments": {}}),
    ])
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.READ_ONLY)
    assert not log.success
    assert "permission" in log.action_results[0].error.lower()

async def test_disabled_pipeline_skipped(executor):
    pipeline = Pipeline(name="disabled", actions=[], enabled=False)
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.ADMIN)
    assert not log.success
    assert "disabled" in log.error.lower()

async def test_execution_log_structure(executor, mock_handlers):
    pipeline = Pipeline(name="log-test", actions=[PipelineAction(action_type=ActionType.NOTIFY, config={})])
    log = await executor.execute(pipeline, _make_ctx(), PermissionLevel.ADMIN)
    assert log.pipeline_id == pipeline.id
    assert log.pipeline_name == pipeline.name
    assert log.started_at is not None
    assert log.finished_at is not None
    assert log.duration_ms >= 0
