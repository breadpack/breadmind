"""Tests for lifecycle hook runner."""
import pytest
from breadmind.core.lifecycle_hooks import (
    LifecycleEvent, LifecycleHookResult, LifecycleHookRunner,
)


@pytest.fixture
def runner():
    return LifecycleHookRunner()


async def test_emit_stop_event(runner):
    called = []

    async def on_stop(data):
        called.append(data)

    runner.on(LifecycleEvent.STOP, on_stop)
    result = await runner.emit(LifecycleEvent.STOP, {"reason": "user_exit"})
    assert result.allow is True
    assert len(called) == 1
    assert called[0]["reason"] == "user_exit"


async def test_user_prompt_submit_modifies_input(runner):
    async def rewrite_prompt(data):
        return LifecycleHookResult(modified_input="sanitized: " + data.get("input", ""))

    runner.on(LifecycleEvent.USER_PROMPT_SUBMIT, rewrite_prompt)
    result = await runner.emit(LifecycleEvent.USER_PROMPT_SUBMIT, {"input": "hello"})
    assert result.modified_input == "sanitized: hello"


async def test_permission_request_returns_decision(runner):
    async def auto_allow(data):
        if data.get("tool") == "file_read":
            return LifecycleHookResult(permission_decision="allow")
        return LifecycleHookResult(permission_decision="ask")

    runner.on(LifecycleEvent.PERMISSION_REQUEST, auto_allow)
    result = await runner.emit(LifecycleEvent.PERMISSION_REQUEST, {"tool": "file_read"})
    assert result.permission_decision == "allow"

    result = await runner.emit(LifecycleEvent.PERMISSION_REQUEST, {"tool": "shell_exec"})
    assert result.permission_decision == "ask"


async def test_multiple_handlers_aggregate(runner):
    async def handler_a(data):
        return LifecycleHookResult(additional_context="context_a ")

    async def handler_b(data):
        return LifecycleHookResult(additional_context="context_b")

    runner.on(LifecycleEvent.SESSION_START, handler_a)
    runner.on(LifecycleEvent.SESSION_START, handler_b)
    result = await runner.emit(LifecycleEvent.SESSION_START)
    assert "context_a" in result.additional_context
    assert "context_b" in result.additional_context


async def test_handler_error_does_not_propagate(runner):
    async def bad_handler(data):
        raise ValueError("boom")

    async def good_handler(data):
        return LifecycleHookResult(additional_context="ok")

    runner.on(LifecycleEvent.PRE_COMPACT, bad_handler)
    runner.on(LifecycleEvent.PRE_COMPACT, good_handler)
    # Should not raise
    result = await runner.emit(LifecycleEvent.PRE_COMPACT)
    assert "ok" in result.additional_context
