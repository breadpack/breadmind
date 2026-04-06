import pytest
from breadmind.webhook.models import (
    WebhookRule, Pipeline, PipelineAction, PipelineContext,
    ActionType, FailureStrategy, PermissionLevel,
)


def test_action_type_enum_values():
    assert ActionType.SEND_TO_AGENT.value == "send_to_agent"
    assert ActionType.CALL_TOOL.value == "call_tool"
    assert ActionType.HTTP_REQUEST.value == "http_request"
    assert ActionType.NOTIFY.value == "notify"
    assert ActionType.TRANSFORM.value == "transform"


def test_failure_strategy_enum_values():
    assert FailureStrategy.STOP.value == "stop"
    assert FailureStrategy.CONTINUE.value == "continue"
    assert FailureStrategy.RETRY.value == "retry"
    assert FailureStrategy.FALLBACK.value == "fallback"


def test_permission_level_ordering():
    assert PermissionLevel.READ_ONLY.can_execute(ActionType.TRANSFORM)
    assert PermissionLevel.READ_ONLY.can_execute(ActionType.NOTIFY)
    assert not PermissionLevel.READ_ONLY.can_execute(ActionType.SEND_TO_AGENT)
    assert PermissionLevel.STANDARD.can_execute(ActionType.SEND_TO_AGENT)
    assert PermissionLevel.STANDARD.can_execute(ActionType.HTTP_REQUEST)
    assert not PermissionLevel.STANDARD.can_execute(ActionType.CALL_TOOL)
    assert PermissionLevel.ELEVATED.can_execute(ActionType.CALL_TOOL)
    assert PermissionLevel.ADMIN.can_execute(ActionType.CALL_TOOL)


def test_webhook_rule_creation():
    rule = WebhookRule(
        name="test rule",
        endpoint_id="ep-1",
        condition="payload.get('action') == 'opened'",
        priority=0,
        pipeline_id="pipe-1",
    )
    assert rule.id
    assert rule.enabled is True
    assert rule.name == "test rule"


def test_pipeline_action_defaults():
    action = PipelineAction(
        action_type=ActionType.NOTIFY,
        config={"channel": "slack", "target": "#general", "message": "hello"},
    )
    assert action.on_failure == FailureStrategy.STOP
    assert action.capture_response is False
    assert action.timeout == 30
    assert action.max_retries == 0


def test_pipeline_creation_with_actions():
    actions = [
        PipelineAction(
            action_type=ActionType.SEND_TO_AGENT,
            config={"message_template": "hello {payload[name]}"},
            capture_response=True,
            response_variable="reply",
        ),
        PipelineAction(
            action_type=ActionType.NOTIFY,
            config={"channel": "slack", "target": "#dev", "message": "{steps[reply]}"},
        ),
    ]
    pipeline = Pipeline(name="test pipeline", actions=actions)
    assert pipeline.id
    assert len(pipeline.actions) == 2
    assert pipeline.enabled is True


def test_pipeline_context_get_variable():
    ctx = PipelineContext(
        payload={"action": "opened", "repo": "breadmind"},
        headers={"x-github-event": "pull_request"},
        endpoint="github-pr",
    )
    ctx.steps["review"] = "Looks good"
    assert ctx.steps["review"] == "Looks good"
    assert ctx.payload["action"] == "opened"


def test_webhook_rule_to_dict_roundtrip():
    rule = WebhookRule(
        name="test",
        endpoint_id="ep-1",
        condition="True",
        priority=0,
        pipeline_id="pipe-1",
    )
    d = rule.to_dict()
    restored = WebhookRule.from_dict(d)
    assert restored.id == rule.id
    assert restored.name == rule.name
    assert restored.condition == rule.condition


def test_pipeline_to_dict_roundtrip():
    pipeline = Pipeline(
        name="test",
        actions=[
            PipelineAction(
                action_type=ActionType.TRANSFORM,
                config={"expression": "payload", "output_variable": "data"},
            ),
        ],
    )
    d = pipeline.to_dict()
    restored = Pipeline.from_dict(d)
    assert restored.id == pipeline.id
    assert len(restored.actions) == 1
    assert restored.actions[0].action_type == ActionType.TRANSFORM
