import pytest
import yaml
from unittest.mock import AsyncMock

from breadmind.webhook.models import WebhookRule, Pipeline, PipelineAction, ActionType
from breadmind.webhook.store import WebhookAutomationStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_setting = AsyncMock(return_value=None)
    db.set_setting = AsyncMock()
    return db

@pytest.fixture
def store(mock_db):
    return WebhookAutomationStore(db=mock_db)

def test_add_and_get_rule(store):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    store.add_rule(rule)
    assert store.get_rule(rule.id) is rule

def test_add_and_get_pipeline(store):
    pipeline = Pipeline(name="p1", actions=[])
    store.add_pipeline(pipeline)
    assert store.get_pipeline(pipeline.id) is pipeline

def test_list_rules_for_endpoint(store):
    r1 = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    r2 = WebhookRule(name="r2", endpoint_id="ep2", condition="True", priority=0, pipeline_id="p2")
    r3 = WebhookRule(name="r3", endpoint_id="ep1", condition="True", priority=1, pipeline_id="p3")
    store.add_rule(r1)
    store.add_rule(r2)
    store.add_rule(r3)
    rules = store.get_rules_for_endpoint("ep1")
    assert len(rules) == 2
    assert all(r.endpoint_id == "ep1" for r in rules)

def test_remove_rule(store):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    store.add_rule(rule)
    assert store.remove_rule(rule.id) is True
    assert store.get_rule(rule.id) is None

def test_remove_pipeline(store):
    pipeline = Pipeline(name="p1", actions=[])
    store.add_pipeline(pipeline)
    assert store.remove_pipeline(pipeline.id) is True
    assert store.get_pipeline(pipeline.id) is None

def test_update_rule(store):
    rule = WebhookRule(name="old", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    store.add_rule(rule)
    store.update_rule(rule.id, name="new", priority=5)
    updated = store.get_rule(rule.id)
    assert updated.name == "new"
    assert updated.priority == 5

def test_update_pipeline(store):
    pipeline = Pipeline(name="old", actions=[])
    store.add_pipeline(pipeline)
    store.update_pipeline(pipeline.id, name="new", description="updated")
    updated = store.get_pipeline(pipeline.id)
    assert updated.name == "new"
    assert updated.description == "updated"

async def test_save_to_db(store, mock_db):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    pipeline = Pipeline(name="p1", actions=[])
    store.add_rule(rule)
    store.add_pipeline(pipeline)
    await store.save()
    assert mock_db.set_setting.await_count == 2

async def test_load_from_db(mock_db):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    pipeline = Pipeline(name="p1", actions=[
        PipelineAction(action_type=ActionType.NOTIFY, config={"channel": "slack", "target": "#t", "message": "hi"}),
    ])
    mock_db.get_setting = AsyncMock(side_effect=lambda key: {
        "webhook_automation_rules": [rule.to_dict()],
        "webhook_automation_pipelines": [pipeline.to_dict()],
    }.get(key))
    store = WebhookAutomationStore(db=mock_db)
    await store.load()
    assert len(store.list_rules()) == 1
    assert len(store.list_pipelines()) == 1

def test_export_yaml(store):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    pipeline = Pipeline(name="p1", actions=[
        PipelineAction(action_type=ActionType.NOTIFY, config={"channel": "slack", "target": "#t", "message": "hi"}),
    ])
    store.add_rule(rule)
    store.add_pipeline(pipeline)
    exported = store.export_yaml()
    data = yaml.safe_load(exported)
    assert "rules" in data and "pipelines" in data
    assert len(data["rules"]) == 1 and len(data["pipelines"]) == 1

def test_import_yaml(store):
    yaml_str = """
rules:
  - name: imported-rule
    endpoint_id: ep1
    condition: "True"
    priority: 0
    pipeline_id: imported-pipe
pipelines:
  - name: imported-pipe
    actions:
      - action_type: notify
        config:
          channel: slack
          target: "#test"
          message: hello
"""
    store.import_yaml(yaml_str)
    rules = store.list_rules()
    pipelines = store.list_pipelines()
    assert len(rules) == 1
    assert rules[0].name == "imported-rule"
    assert len(pipelines) == 1
    assert pipelines[0].name == "imported-pipe"
