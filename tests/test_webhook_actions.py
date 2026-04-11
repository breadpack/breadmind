"""Tests for webhook action handler system."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from breadmind.webhook.models import PipelineAction, PipelineContext, ActionType
from breadmind.webhook.actions.base import ActionHandler, ActionResult, resolve_template
from breadmind.webhook.actions.agent_action import AgentActionHandler
from breadmind.webhook.actions.tool_action import ToolActionHandler
from breadmind.webhook.actions.http_action import HttpActionHandler
from breadmind.webhook.actions.notify_action import NotifyActionHandler
from breadmind.webhook.actions.transform_action import TransformActionHandler


def test_resolve_template_simple():
    ctx = PipelineContext(payload={"name": "test-repo", "number": 42}, headers={}, endpoint="github")
    result = resolve_template("PR #{{ payload.number }} in {{ payload.name }}", ctx)
    assert result == "PR #42 in test-repo"

def test_resolve_template_with_steps():
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    ctx.steps["review"] = "Looks good"
    result = resolve_template("Result: {{ steps.review }}", ctx)
    assert result == "Result: Looks good"

def test_resolve_template_nested_dict():
    ctx = PipelineContext(payload={"repo": {"full_name": "org/repo"}}, headers={}, endpoint="test")
    result = resolve_template("Repo: {{ payload.repo.full_name }}", ctx)
    assert result == "Repo: org/repo"

def test_action_result_success():
    r = ActionResult(success=True, output="done")
    assert r.success and r.output == "done"

def test_action_result_failure():
    r = ActionResult(success=False, output="", error="timeout")
    assert not r.success and r.error == "timeout"

async def test_transform_action():
    action = PipelineAction(action_type=ActionType.TRANSFORM, config={"expression": "{'priority': 'high' if payload.get('urgent') else 'low'}", "output_variable": "parsed"})
    ctx = PipelineContext(payload={"urgent": True}, headers={}, endpoint="test")
    handler = TransformActionHandler()
    result = await handler.execute(action, ctx)
    assert result.success
    assert ctx.steps["parsed"] == {"priority": "high"}

async def test_transform_action_blocked_import():
    action = PipelineAction(action_type=ActionType.TRANSFORM, config={"expression": "__import__('os')", "output_variable": "x"})
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = TransformActionHandler()
    result = await handler.execute(action, ctx)
    assert not result.success
    assert "forbidden" in result.error.lower()

async def test_agent_action_fire_and_forget():
    mock_handler = AsyncMock(return_value="Agent says hello")
    action = PipelineAction(action_type=ActionType.SEND_TO_AGENT, config={"message_template": "Hello from webhook"}, capture_response=False)
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = AgentActionHandler(message_handler=mock_handler)
    result = await handler.execute(action, ctx)
    assert result.success
    mock_handler.assert_awaited_once()

async def test_agent_action_capture_response():
    mock_handler = AsyncMock(return_value="Review complete")
    action = PipelineAction(action_type=ActionType.SEND_TO_AGENT, config={"message_template": "Review PR"}, capture_response=True, response_variable="review_result")
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = AgentActionHandler(message_handler=mock_handler)
    result = await handler.execute(action, ctx)
    assert result.success
    assert ctx.steps["review_result"] == "Review complete"

async def test_tool_action_calls_registry():
    mock_registry = MagicMock()
    mock_tool_fn = AsyncMock(return_value=MagicMock(success=True, output="pod-1\npod-2"))
    mock_registry.get_tool.return_value = mock_tool_fn
    action = PipelineAction(action_type=ActionType.CALL_TOOL, config={"tool_name": "shell_execute", "arguments": {"command": "kubectl get pods"}}, capture_response=True, response_variable="pods")
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = ToolActionHandler(tool_registry=mock_registry)
    result = await handler.execute(action, ctx)
    assert result.success
    assert ctx.steps["pods"] == "pod-1\npod-2"

async def test_tool_action_missing_tool():
    mock_registry = MagicMock()
    mock_registry.get_tool.return_value = None
    action = PipelineAction(action_type=ActionType.CALL_TOOL, config={"tool_name": "nonexistent", "arguments": {}})
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = ToolActionHandler(tool_registry=mock_registry)
    result = await handler.execute(action, ctx)
    assert not result.success
    assert "not found" in result.error.lower()

async def test_http_action_success():
    action = PipelineAction(action_type=ActionType.HTTP_REQUEST, config={"method": "POST", "url": "https://example.com/api", "body": {"text": "hello"}}, capture_response=True, response_variable="api_response")
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = HttpActionHandler()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"ok": true}')
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session
        result = await handler.execute(action, ctx)
    assert result.success
    assert ctx.steps["api_response"] == '{"ok": true}'

async def test_notify_action_with_router():
    mock_router = MagicMock()
    mock_send = AsyncMock()
    mock_router.send_to_channel = mock_send
    action = PipelineAction(action_type=ActionType.NOTIFY, config={"channel": "slack", "target": "#devops", "message": "Deploy done"})
    ctx = PipelineContext(payload={}, headers={}, endpoint="test")
    handler = NotifyActionHandler(message_router=mock_router)
    result = await handler.execute(action, ctx)
    assert result.success
    mock_send.assert_awaited_once_with("slack", "#devops", "Deploy done")
