import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from breadmind.webhook.models import WebhookRule, Pipeline
from breadmind.webhook.store import WebhookAutomationStore


@pytest.fixture
def store():
    return WebhookAutomationStore()

@pytest.fixture
def app(store):
    from breadmind.web.routes.webhook_automation import setup_webhook_automation_routes
    app = FastAPI()
    mock_app_state = MagicMock()
    mock_app_state._webhook_automation_store = store
    app.state.app_state = mock_app_state
    setup_webhook_automation_routes(app, mock_app_state)
    return app

@pytest.fixture
def client(app):
    return TestClient(app)

def test_list_rules_empty(client):
    resp = client.get("/api/webhook/rules")
    assert resp.status_code == 200
    assert resp.json()["rules"] == []

def test_create_rule(client, store):
    resp = client.post("/api/webhook/rules", json={
        "name": "test-rule", "endpoint_id": "ep1",
        "condition": "payload.get('action') == 'opened'",
        "priority": 0, "pipeline_id": "p1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["rule"]["name"] == "test-rule"
    assert len(store.list_rules()) == 1

def test_get_rule(client, store):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    store.add_rule(rule)
    resp = client.get(f"/api/webhook/rules/{rule.id}")
    assert resp.status_code == 200
    assert resp.json()["rule"]["name"] == "r1"

def test_delete_rule(client, store):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1")
    store.add_rule(rule)
    resp = client.delete(f"/api/webhook/rules/{rule.id}")
    assert resp.status_code == 200
    assert len(store.list_rules()) == 0

def test_list_pipelines_empty(client):
    resp = client.get("/api/webhook/pipelines")
    assert resp.status_code == 200
    assert resp.json()["pipelines"] == []

def test_create_pipeline(client, store):
    resp = client.post("/api/webhook/pipelines", json={
        "name": "test-pipeline", "description": "test",
        "actions": [{"action_type": "notify", "config": {"channel": "slack", "target": "#t", "message": "hi"}}],
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(store.list_pipelines()) == 1

def test_get_pipeline(client, store):
    pipeline = Pipeline(name="p1", actions=[])
    store.add_pipeline(pipeline)
    resp = client.get(f"/api/webhook/pipelines/{pipeline.id}")
    assert resp.status_code == 200
    assert resp.json()["pipeline"]["name"] == "p1"

def test_delete_pipeline(client, store):
    pipeline = Pipeline(name="p1", actions=[])
    store.add_pipeline(pipeline)
    resp = client.delete(f"/api/webhook/pipelines/{pipeline.id}")
    assert resp.status_code == 200
    assert len(store.list_pipelines()) == 0

def test_export_yaml(client, store):
    store.add_rule(WebhookRule(name="r1", endpoint_id="ep1", condition="True", priority=0, pipeline_id="p1"))
    resp = client.get("/api/webhook/export")
    assert resp.status_code == 200
    assert "rules" in resp.text

def test_import_yaml(client, store):
    yaml_content = "rules:\n  - name: imported\n    endpoint_id: ep1\n    condition: 'True'\n    priority: 0\n    pipeline_id: p1\npipelines: []\n"
    resp = client.post("/api/webhook/import", content=yaml_content, headers={"Content-Type": "text/yaml"})
    assert resp.status_code == 200
    assert len(store.list_rules()) == 1

def test_test_rule_dry_run(client, store):
    rule = WebhookRule(name="r1", endpoint_id="ep1", condition="payload.get('action') == 'opened'", priority=0, pipeline_id="p1")
    store.add_rule(rule)
    resp = client.post(f"/api/webhook/rules/{rule.id}/test", json={"payload": {"action": "opened"}, "headers": {}})
    assert resp.status_code == 200
    assert resp.json()["matched"] is True
