import asyncio
import hashlib
import hmac
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from breadmind.core.subagent import SubAgentManager
from breadmind.web.webhook import WebhookManager, WebhookEndpoint
from breadmind.web.app import WebApp


# ── SubAgentManager tests ──


@pytest.mark.asyncio
async def test_spawn_creates_task():
    mgr = SubAgentManager()
    mgr.set_message_handler(AsyncMock(return_value="done"))
    task = await mgr.spawn(task="hello")
    assert task.id is not None
    assert task.task == "hello"
    assert task.status in ("pending", "running", "completed")


@pytest.mark.asyncio
async def test_spawn_executes_with_mock_handler():
    handler = AsyncMock(return_value="result-42")
    mgr = SubAgentManager()
    mgr.set_message_handler(handler)
    task = await mgr.spawn(task="do something", parent_id="p1", model="test-model")
    # Wait for background task
    await asyncio.sleep(0.1)
    info = mgr.get_task(task.id)
    assert info is not None
    assert info["status"] == "completed"
    assert info["result"] == "result-42"
    assert info["parent_id"] == "p1"
    assert info["model"] == "test-model"
    handler.assert_called_once()


@pytest.mark.asyncio
async def test_spawn_no_handler_fails():
    mgr = SubAgentManager()
    task = await mgr.spawn(task="test")
    await asyncio.sleep(0.1)
    info = mgr.get_task(task.id)
    assert info["status"] == "failed"
    assert "No message handler" in info["result"]


@pytest.mark.asyncio
async def test_spawn_handler_exception():
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    mgr = SubAgentManager()
    mgr.set_message_handler(handler)
    task = await mgr.spawn(task="fail")
    await asyncio.sleep(0.1)
    info = mgr.get_task(task.id)
    assert info["status"] == "failed"
    assert "boom" in info["result"]


@pytest.mark.asyncio
async def test_spawn_sync_handler():
    handler = MagicMock(return_value="sync-result")
    mgr = SubAgentManager()
    mgr.set_message_handler(handler)
    task = await mgr.spawn(task="sync test")
    await asyncio.sleep(0.1)
    info = mgr.get_task(task.id)
    assert info["status"] == "completed"
    assert info["result"] == "sync-result"


@pytest.mark.asyncio
async def test_list_tasks():
    mgr = SubAgentManager()
    mgr.set_message_handler(AsyncMock(return_value="ok"))
    await mgr.spawn(task="task1")
    await mgr.spawn(task="task2")
    await asyncio.sleep(0.1)
    tasks = mgr.list_tasks()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_get_task_not_found():
    mgr = SubAgentManager()
    assert mgr.get_task("nonexistent") is None


@pytest.mark.asyncio
async def test_get_status():
    mgr = SubAgentManager()
    mgr.set_message_handler(AsyncMock(return_value="ok"))
    await mgr.spawn(task="t1")
    await mgr.spawn(task="t2")
    await asyncio.sleep(0.1)
    status = mgr.get_status()
    assert status["total"] == 2
    assert status["completed"] == 2
    assert status["pending"] == 0
    assert status["failed"] == 0


# ── WebhookManager tests ──


@pytest.mark.asyncio
async def test_webhook_add_remove_endpoints():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="Test", path="test-hook",
                         event_type="generic", action="Got: {payload}")
    wm.add_endpoint(ep)
    endpoints = wm.get_endpoints()
    assert len(endpoints) == 1
    assert endpoints[0]["id"] == "ep1"

    assert wm.remove_endpoint("ep1") is True
    assert wm.remove_endpoint("ep1") is False
    assert len(wm.get_endpoints()) == 0


@pytest.mark.asyncio
async def test_webhook_handle_valid_path():
    handler = AsyncMock(return_value="processed")
    wm = WebhookManager()
    wm.set_message_handler(handler)
    ep = WebhookEndpoint(id="ep1", name="Test", path="my-hook",
                         event_type="generic", action="Received: {payload}")
    wm.add_endpoint(ep)

    result = await wm.handle_webhook("my-hook", {"key": "value"})
    assert result["status"] == "ok"
    assert "processed" in result["response"]
    handler.assert_called_once()
    assert ep.received_count == 1


@pytest.mark.asyncio
async def test_webhook_handle_unknown_path():
    wm = WebhookManager()
    result = await wm.handle_webhook("unknown", {})
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_webhook_handle_disabled():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="Test", path="disabled-hook",
                         event_type="generic", action="x", enabled=False)
    wm.add_endpoint(ep)
    result = await wm.handle_webhook("disabled-hook", {})
    assert result["status"] == "disabled"


@pytest.mark.asyncio
async def test_webhook_handle_no_handler():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="Test", path="no-handler",
                         event_type="generic", action="x")
    wm.add_endpoint(ep)
    result = await wm.handle_webhook("no-handler", {})
    assert result["status"] == "ok"
    assert "no handler" in result.get("message", "").lower()


@pytest.mark.asyncio
async def test_webhook_handle_sync_handler():
    handler = MagicMock(return_value="sync-done")
    wm = WebhookManager()
    wm.set_message_handler(handler)
    ep = WebhookEndpoint(id="ep1", name="Test", path="sync-hook",
                         event_type="generic", action="Got: {payload}")
    wm.add_endpoint(ep)
    result = await wm.handle_webhook("sync-hook", {"data": 1})
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_handler_exception():
    handler = AsyncMock(side_effect=RuntimeError("webhook boom"))
    wm = WebhookManager()
    wm.set_message_handler(handler)
    ep = WebhookEndpoint(id="ep1", name="Test", path="err-hook",
                         event_type="generic", action="x")
    wm.add_endpoint(ep)
    result = await wm.handle_webhook("err-hook", {})
    assert result["status"] == "error"
    assert "webhook boom" in result["error"]


def test_extract_summary_github_pr():
    wm = WebhookManager()
    payload = {
        "action": "opened",
        "pull_request": {"number": 42, "title": "Fix bug"},
    }
    summary = wm._extract_summary("github", payload)
    assert "PR #42" in summary
    assert "Fix bug" in summary
    assert "opened" in summary


def test_extract_summary_github_push():
    wm = WebhookManager()
    payload = {
        "ref": "refs/heads/main",
        "commits": [{"id": "abc"}, {"id": "def"}],
    }
    summary = wm._extract_summary("github", payload)
    assert "Push to refs/heads/main" in summary
    assert "2 commits" in summary


def test_extract_summary_github_issue():
    wm = WebhookManager()
    payload = {
        "action": "closed",
        "issue": {"number": 10, "title": "Bug report"},
    }
    summary = wm._extract_summary("github", payload)
    assert "Issue #10" in summary


def test_extract_summary_gitlab_mr():
    wm = WebhookManager()
    payload = {
        "object_kind": "merge_request",
        "object_attributes": {"iid": 5, "title": "Feature X"},
    }
    summary = wm._extract_summary("gitlab", payload)
    assert "MR !5" in summary
    assert "Feature X" in summary


def test_extract_summary_ci():
    wm = WebhookManager()
    payload = {"name": "build-123", "status": "success"}
    summary = wm._extract_summary("ci", payload)
    assert "build-123" in summary
    assert "success" in summary


def test_extract_summary_unknown_type():
    wm = WebhookManager()
    summary = wm._extract_summary("unknown", {"data": 1})
    assert summary == ""


@pytest.mark.asyncio
async def test_get_event_log():
    handler = AsyncMock(return_value="ok")
    wm = WebhookManager()
    wm.set_message_handler(handler)
    ep = WebhookEndpoint(id="ep1", name="Log Test", path="log-hook",
                         event_type="generic", action="x")
    wm.add_endpoint(ep)
    await wm.handle_webhook("log-hook", {"a": 1})
    await wm.handle_webhook("log-hook", {"b": 2})
    log = wm.get_event_log()
    assert len(log) == 2
    assert log[0]["endpoint"] == "Log Test"


# ── Webhook HMAC verification tests ──


def test_verify_secret_github_correct():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="GH", path="gh", event_type="github",
                         action="x", secret="mysecret")
    payload = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(b"mysecret", payload, hashlib.sha256).hexdigest()
    headers = {"x-hub-signature-256": sig}
    assert wm._verify_secret(ep, payload, headers) is True


def test_verify_secret_github_wrong():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="GH", path="gh", event_type="github",
                         action="x", secret="mysecret")
    payload = b'{"action":"opened"}'
    headers = {"x-hub-signature-256": "sha256=wrong"}
    assert wm._verify_secret(ep, payload, headers) is False


def test_verify_secret_gitlab_token():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="GL", path="gl", event_type="gitlab",
                         action="x", secret="gitlab-token-123")
    headers = {"x-gitlab-token": "gitlab-token-123"}
    assert wm._verify_secret(ep, b"", headers) is True


def test_verify_secret_gitlab_token_wrong():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="GL", path="gl", event_type="gitlab",
                         action="x", secret="gitlab-token-123")
    headers = {"x-gitlab-token": "wrong-token"}
    assert wm._verify_secret(ep, b"", headers) is False


def test_verify_secret_generic():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="Gen", path="gen", event_type="generic",
                         action="x", secret="my-generic-secret")
    headers = {"x-webhook-secret": "my-generic-secret"}
    assert wm._verify_secret(ep, b"", headers) is True


def test_verify_secret_no_secret_configured():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="Open", path="open", event_type="generic",
                         action="x", secret="")
    assert wm._verify_secret(ep, b"", {}) is True


def test_verify_secret_secret_set_no_header_rejects():
    wm = WebhookManager()
    ep = WebhookEndpoint(id="ep1", name="Sec", path="sec", event_type="generic",
                         action="x", secret="some-secret")
    assert wm._verify_secret(ep, b"", {}) is False


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_signature():
    handler = AsyncMock(return_value="ok")
    wm = WebhookManager()
    wm.set_message_handler(handler)
    ep = WebhookEndpoint(id="ep1", name="Secure", path="secure-hook",
                         event_type="github", action="x", secret="topsecret")
    wm.add_endpoint(ep)
    result = await wm.handle_webhook("secure-hook", {"data": 1}, headers={}, payload_bytes=b'{"data": 1}')
    assert result["status"] == "unauthorized"
    assert "Invalid webhook signature" in result["error"]
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_accepts_valid_signature():
    handler = AsyncMock(return_value="processed")
    wm = WebhookManager()
    wm.set_message_handler(handler)
    ep = WebhookEndpoint(id="ep1", name="Secure", path="secure-hook",
                         event_type="github", action="Got: {payload}", secret="topsecret")
    wm.add_endpoint(ep)
    payload_bytes = b'{"data": 1}'
    sig = "sha256=" + hmac.new(b"topsecret", payload_bytes, hashlib.sha256).hexdigest()
    result = await wm.handle_webhook(
        "secure-hook", {"data": 1},
        headers={"x-hub-signature-256": sig},
        payload_bytes=payload_bytes,
    )
    assert result["status"] == "ok"
    handler.assert_called_once()


# ── Web API endpoint tests ──


@pytest.fixture
def web_app_with_managers():
    mock_registry = MagicMock()
    mock_registry.get_all_definitions.return_value = []
    mock_registry.get_tool_source.return_value = "builtin"

    mock_mcp = MagicMock()
    mock_mcp.list_servers = AsyncMock(return_value=[])

    subagent_mgr = SubAgentManager()
    subagent_mgr.set_message_handler(AsyncMock(return_value="agent-response"))

    webhook_mgr = WebhookManager()
    webhook_mgr.set_message_handler(AsyncMock(return_value="webhook-response"))

    app = WebApp(
        message_handler=AsyncMock(return_value="test response"),
        tool_registry=mock_registry,
        mcp_manager=mock_mcp,
        subagent_manager=subagent_mgr,
        webhook_manager=webhook_mgr,
    )
    return app, subagent_mgr, webhook_mgr


@pytest.fixture
def client_with_managers(web_app_with_managers):
    app, _, _ = web_app_with_managers
    return TestClient(app.app)


def test_api_spawn_subagent(client_with_managers):
    resp = client_with_managers.post("/api/subagent/spawn", json={"task": "hello world"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "task_id" in data


def test_api_list_subagent_tasks(client_with_managers):
    client_with_managers.post("/api/subagent/spawn", json={"task": "t1"})
    resp = client_with_managers.get("/api/subagent/tasks")
    assert resp.status_code == 200
    assert "tasks" in resp.json()


def test_api_get_subagent_task(client_with_managers):
    resp = client_with_managers.post("/api/subagent/spawn", json={"task": "t1"})
    task_id = resp.json()["task_id"]
    resp2 = client_with_managers.get(f"/api/subagent/tasks/{task_id}")
    assert resp2.status_code == 200
    assert resp2.json()["task"]["id"] == task_id


def test_api_get_subagent_task_not_found(client_with_managers):
    resp = client_with_managers.get("/api/subagent/tasks/nonexistent")
    assert resp.status_code == 404


def test_api_subagent_status(client_with_managers):
    resp = client_with_managers.get("/api/subagent/status")
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_api_subagent_no_manager():
    app = WebApp()
    client = TestClient(app.app)
    resp = client.post("/api/subagent/spawn", json={"task": "x"})
    assert resp.status_code == 503
    resp = client.get("/api/subagent/tasks")
    assert resp.json()["tasks"] == []
    resp = client.get("/api/subagent/status")
    assert resp.json()["status"]["total"] == 0


def test_api_webhook_list_endpoints(client_with_managers):
    resp = client_with_managers.get("/api/webhook/endpoints")
    assert resp.status_code == 200
    assert resp.json()["endpoints"] == []


def test_api_webhook_add_endpoint(client_with_managers):
    resp = client_with_managers.post("/api/webhook/endpoints", json={
        "name": "GitHub", "path": "github", "event_type": "github",
        "action": "PR event: {payload}",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["endpoint"]["path"] == "github"
    assert "/api/webhook/receive/github" in data["endpoint"]["url"]

    # Verify it appears in list
    resp2 = client_with_managers.get("/api/webhook/endpoints")
    assert len(resp2.json()["endpoints"]) == 1


def test_api_webhook_delete_endpoint(web_app_with_managers):
    _, _, webhook_mgr = web_app_with_managers
    app, _, _ = web_app_with_managers
    client = TestClient(app.app)

    # Add first
    client.post("/api/webhook/endpoints", json={
        "id": "del-me", "name": "ToDelete", "path": "del-hook",
        "event_type": "generic", "action": "x",
    })
    resp = client.delete("/api/webhook/endpoints/del-me")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Delete again -> not_found
    resp = client.delete("/api/webhook/endpoints/del-me")
    assert resp.json()["status"] == "not_found"


def test_api_webhook_receive(web_app_with_managers):
    app, _, webhook_mgr = web_app_with_managers
    client = TestClient(app.app)

    # Add endpoint
    ep = WebhookEndpoint(id="rcv1", name="Receiver", path="test-receive",
                         event_type="generic", action="Got: {payload}")
    webhook_mgr.add_endpoint(ep)

    resp = client.post("/api/webhook/receive/test-receive", json={"event": "push"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_webhook_receive_not_found(client_with_managers):
    resp = client_with_managers.post("/api/webhook/receive/nope", json={})
    assert resp.status_code == 404


def test_api_webhook_log(client_with_managers):
    resp = client_with_managers.get("/api/webhook/log")
    assert resp.status_code == 200
    assert "events" in resp.json()


def test_api_webhook_no_manager():
    app = WebApp()
    client = TestClient(app.app)
    resp = client.get("/api/webhook/endpoints")
    assert resp.json()["endpoints"] == []
    resp = client.post("/api/webhook/endpoints", json={"name": "x"})
    assert resp.status_code == 503
    resp = client.post("/api/webhook/receive/x", json={})
    assert resp.status_code == 503
    resp = client.get("/api/webhook/log")
    assert resp.json()["events"] == []
