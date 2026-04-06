import pytest
from breadmind.webhook.rule_engine import RuleEngine, ConditionError
from breadmind.webhook.models import WebhookRule


@pytest.fixture
def engine():
    return RuleEngine()


def test_simple_equality(engine):
    result = engine.evaluate_condition(
        "payload.get('action') == 'opened'",
        payload={"action": "opened"},
        headers={},
    )
    assert result is True


def test_simple_inequality(engine):
    result = engine.evaluate_condition(
        "payload.get('action') == 'opened'",
        payload={"action": "closed"},
        headers={},
    )
    assert result is False


def test_nested_access(engine):
    result = engine.evaluate_condition(
        "payload.get('pull_request', {}).get('draft') is False",
        payload={"pull_request": {"draft": False}},
        headers={},
    )
    assert result is True


def test_in_operator(engine):
    result = engine.evaluate_condition(
        "'bug' in payload.get('labels', [])",
        payload={"labels": ["bug", "urgent"]},
        headers={},
    )
    assert result is True


def test_header_access(engine):
    result = engine.evaluate_condition(
        "headers.get('x-github-event') == 'pull_request'",
        payload={},
        headers={"x-github-event": "pull_request"},
    )
    assert result is True


def test_complex_condition(engine):
    result = engine.evaluate_condition(
        "payload.get('action') == 'opened' and len(payload.get('commits', [])) > 0",
        payload={"action": "opened", "commits": [{"id": "abc"}]},
        headers={},
    )
    assert result is True


def test_list_comprehension(engine):
    result = engine.evaluate_condition(
        "'bug' in [l['name'] for l in payload.get('labels', [])]",
        payload={"labels": [{"name": "bug"}, {"name": "feature"}]},
        headers={},
    )
    assert result is True


def test_blocked_import(engine):
    with pytest.raises(ConditionError, match="forbidden"):
        engine.evaluate_condition("__import__('os').system('ls')", payload={}, headers={})


def test_blocked_dunder(engine):
    with pytest.raises(ConditionError, match="forbidden"):
        engine.evaluate_condition("payload.__class__.__bases__", payload={}, headers={})


def test_blocked_exec(engine):
    with pytest.raises(ConditionError, match="forbidden"):
        engine.evaluate_condition("exec('print(1)')", payload={}, headers={})


def test_blocked_eval(engine):
    with pytest.raises(ConditionError, match="forbidden"):
        engine.evaluate_condition("eval('1+1')", payload={}, headers={})


def test_match_rules_priority_order(engine):
    rules = [
        WebhookRule(name="low", endpoint_id="ep1", condition="True", priority=10, pipeline_id="p-low"),
        WebhookRule(name="high", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p-high"),
        WebhookRule(name="mid", endpoint_id="ep1", condition="True", priority=5, pipeline_id="p-mid"),
    ]
    matched = engine.match_rules(rules, payload={}, headers={})
    assert matched is not None
    assert matched.pipeline_id == "p-high"


def test_match_rules_skips_false(engine):
    rules = [
        WebhookRule(name="no-match", endpoint_id="ep1", condition="False", priority=0, pipeline_id="p1"),
        WebhookRule(name="match", endpoint_id="ep1", condition="True", priority=1, pipeline_id="p2"),
    ]
    matched = engine.match_rules(rules, payload={}, headers={})
    assert matched is not None
    assert matched.pipeline_id == "p2"


def test_match_rules_none_when_no_match(engine):
    rules = [
        WebhookRule(name="no", endpoint_id="ep1", condition="False", priority=0, pipeline_id="p1"),
    ]
    matched = engine.match_rules(rules, payload={}, headers={})
    assert matched is None


def test_match_rules_skips_disabled(engine):
    rules = [
        WebhookRule(name="disabled", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1", enabled=False),
    ]
    matched = engine.match_rules(rules, payload={}, headers={})
    assert matched is None


def test_condition_error_on_runtime_exception(engine):
    with pytest.raises(ConditionError):
        engine.evaluate_condition("1 / 0", payload={}, headers={})
