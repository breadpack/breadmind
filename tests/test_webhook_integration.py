import pytest
from unittest.mock import AsyncMock

from breadmind.web.webhook import WebhookEndpoint, WebhookManager
from breadmind.webhook.models import (
    WebhookRule, Pipeline, PipelineAction,
    ActionType,
)
from breadmind.webhook.store import WebhookAutomationStore
from breadmind.webhook.rule_engine import RuleEngine
from breadmind.webhook.pipeline_executor import PipelineExecutor, ExecutionLog


@pytest.fixture
def store():
    return WebhookAutomationStore()

@pytest.fixture
def rule_engine():
    return RuleEngine()

@pytest.fixture
def mock_executor():
    ex = AsyncMock(spec=PipelineExecutor)
    ex.execute = AsyncMock(return_value=ExecutionLog(pipeline_id="p1", pipeline_name="test", success=True))
    return ex

@pytest.fixture
def manager(store, rule_engine, mock_executor):
    mgr = WebhookManager()
    mgr.set_automation(store=store, rule_engine=rule_engine, pipeline_executor=mock_executor)
    mgr.set_message_handler(AsyncMock(return_value="agent response"))
    ep = WebhookEndpoint(id="ep1", name="GitHub", path="github", event_type="github", action="Webhook: {payload}")
    mgr.add_endpoint(ep)
    return mgr

async def test_webhook_with_matching_rule(manager, store, mock_executor):
    pipeline = Pipeline(name="pr-review", actions=[
        PipelineAction(action_type=ActionType.NOTIFY, config={}),
    ])
    store.add_pipeline(pipeline)
    rule = WebhookRule(name="pr-opened", endpoint_id="ep1",
        condition="payload.get('action') == 'opened'", priority=0, pipeline_id=pipeline.id)
    store.add_rule(rule)
    result = await manager.handle_webhook("github", {"action": "opened"}, {"x-webhook-secret": ""}, b"")
    assert result["status"] == "ok"
    mock_executor.execute.assert_awaited_once()

async def test_webhook_fallback_forward_to_agent(manager, store):
    result = await manager.handle_webhook("github", {"action": "closed"}, {"x-webhook-secret": ""}, b"")
    assert result["status"] == "ok"
    assert manager._message_handler.await_count > 0

async def test_webhook_fallback_drop(manager, store):
    ep = manager.get_endpoint_by_path("github")
    ep.fallback_strategy = "drop"
    result = await manager.handle_webhook("github", {"action": "unknown"}, {"x-webhook-secret": ""}, b"")
    assert result["status"] == "ok"
    assert "dropped" in result.get("message", "").lower()
