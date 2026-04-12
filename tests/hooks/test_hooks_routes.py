import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breadmind.hooks import HookEvent
from breadmind.hooks.db_store import HookOverride
from breadmind.hooks.handler import PythonHook
from breadmind.hooks.registry import HookRegistry
from breadmind.web.routes.hooks import router as hooks_router


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows
    async def list_all(self):
        return list(self._rows)
    async def list_by_event(self, event):
        return [r for r in self._rows if r.event == event]
    async def insert(self, ov):
        self._rows.append(ov)
    async def delete(self, hook_id):
        self._rows = [r for r in self._rows if r.hook_id != hook_id]


@pytest.fixture
def app_with_hooks():
    app = FastAPI()
    app.state.hook_registry = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="user:block-rm", source="user", event="pre_tool_use",
            type="shell", tool_pattern="shell_*", priority=100, enabled=True,
            config_json={"command": "exit 1"},
        ),
    ]))
    app.state.hook_registry.add_manifest_hook(PythonHook(
        name="demo:inject-ns",
        event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: None,
        priority=50,
    ))
    app.include_router(hooks_router)
    return app


def test_list_returns_merged_manifest_and_db(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.get("/api/hooks/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    by_id = {h["hook_id"]: h for h in data["hooks"]}
    assert "demo:inject-ns" in by_id
    assert "user:block-rm" in by_id
    assert by_id["demo:inject-ns"]["source"] == "manifest"
    assert by_id["user:block-rm"]["source"] == "db"
    assert by_id["demo:inject-ns"]["type"] == "python"
    assert by_id["user:block-rm"]["type"] == "shell"


def test_delete_db_hook(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.delete("/api/hooks/user:block-rm")
    assert resp.status_code == 200
    resp = client.get("/api/hooks/list")
    ids = [h["hook_id"] for h in resp.json()["hooks"]]
    assert "user:block-rm" not in ids


def test_delete_manifest_hook_forbidden(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.delete("/api/hooks/demo:inject-ns")
    assert resp.status_code == 400


def test_create_new_shell_hook(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.post("/api/hooks/", json={
        "hook_id": "user:new",
        "event": "pre_tool_use",
        "type": "shell",
        "tool_pattern": "*",
        "priority": 10,
        "enabled": True,
        "config_json": {"command": "echo ok"},
    })
    assert resp.status_code == 200
    resp = client.get("/api/hooks/list")
    ids = [h["hook_id"] for h in resp.json()["hooks"]]
    assert "user:new" in ids


def test_create_rejects_unknown_event(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.post("/api/hooks/", json={
        "hook_id": "bad",
        "event": "not_an_event",
        "type": "shell",
        "priority": 0,
        "enabled": True,
        "config_json": {"command": "x"},
    })
    assert resp.status_code == 400


def test_traces_endpoint_returns_list(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.get("/api/hooks/traces?limit=10")
    assert resp.status_code == 200
    assert "entries" in resp.json()


def test_stats_endpoint_returns_aggregates(app_with_hooks):
    client = TestClient(app_with_hooks)
    resp = client.get("/api/hooks/stats")
    assert resp.status_code == 200
    assert "stats" in resp.json()


def test_main_app_registers_hooks_router():
    """Ensure the main app bootstrap actually includes the hooks router."""
    try:
        from breadmind.web.app import WebApp
    except Exception:
        pytest.skip("main app module not importable in test env")
    try:
        web = WebApp()
        app = web.app
    except Exception:
        pytest.skip("WebApp() not constructible without full context")
    paths = {getattr(r, "path", "") for r in app.routes}
    assert any("/api/hooks/list" in p for p in paths), (
        f"hooks router not registered; found paths: {sorted(paths)[:20]}"
    )
