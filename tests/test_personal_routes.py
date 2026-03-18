"""Personal assistant REST API tests."""
import pytest
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from breadmind.web.routes.personal import router
    from breadmind.personal.adapters.base import AdapterRegistry

    app = FastAPI()
    app.include_router(router)

    registry = AdapterRegistry()

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[])
    task_adapter.create_item = AsyncMock(return_value="new-task-id")
    task_adapter.update_item = AsyncMock(return_value=True)
    task_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(task_adapter)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    event_adapter.create_item = AsyncMock(return_value="new-event-id")
    event_adapter.update_item = AsyncMock(return_value=True)
    event_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(event_adapter)

    app.state.adapter_registry = registry
    return TestClient(app)


def test_list_tasks_empty(client):
    resp = client.get("/api/personal/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_task(client):
    resp = client.post("/api/personal/tasks", json={"title": "Buy milk"})
    assert resp.status_code == 201
    assert resp.json()["id"] == "new-task-id"


def test_update_task(client):
    resp = client.patch("/api/personal/tasks/t1", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["updated"] is True


def test_delete_task(client):
    resp = client.delete("/api/personal/tasks/t1")
    assert resp.status_code == 200


def test_list_events_empty(client):
    resp = client.get("/api/personal/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_event(client):
    resp = client.post("/api/personal/events", json={
        "title": "Standup", "start_at": "2026-03-18T09:00:00Z"})
    assert resp.status_code == 201
    assert resp.json()["id"] == "new-event-id"


def test_no_registry_returns_503(client):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from breadmind.web.routes.personal import router

    app = FastAPI()
    app.include_router(router)
    tc = TestClient(app)
    resp = tc.get("/api/personal/tasks")
    assert resp.status_code == 503
