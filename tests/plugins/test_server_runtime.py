import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.plugins.builtin.runtimes.server_runtime import ServerRuntime


@pytest.fixture
def agent():
    a = MagicMock()
    a.name = "TestBot"
    a.run = AsyncMock(return_value="Hello from server!")
    return a


def test_server_runtime_creation(agent):
    rt = ServerRuntime(agent=agent, host="127.0.0.1", port=9000)
    assert rt._host == "127.0.0.1"
    assert rt._port == 9000


def test_create_app(agent):
    rt = ServerRuntime(agent=agent)
    app = rt.create_app()
    assert app is not None
    assert app.title == "BreadMind v2 - TestBot"
    # Check routes exist
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/api/chat" in routes
    assert "/ws/chat" in routes


@pytest.mark.asyncio
async def test_health_endpoint(agent):
    from fastapi.testclient import TestClient
    rt = ServerRuntime(agent=agent)
    app = rt.create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["agent"] == "TestBot"


@pytest.mark.asyncio
async def test_chat_endpoint(agent):
    from fastapi.testclient import TestClient
    rt = ServerRuntime(agent=agent)
    app = rt.create_app()
    client = TestClient(app)
    resp = client.post("/api/chat", json={"message": "hello", "user": "tester"})
    assert resp.status_code == 200
    assert resp.json()["response"] == "Hello from server!"
