"""Verify messenger v1 router is mounted on the main BreadMind FastAPI app.

Closes M2a dep #1: rt-relay integration tests need the messenger HTTP API
reachable on the same FastAPI app the relay's BackfillSince calls back into.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_messenger_router_mounted():
    """The OpenAPI schema must include at least one /api/workspaces/... path.

    Routes register at the un-versioned `/api` prefix; the versioning
    middleware rewrites `/api/v1/...` requests to that prefix at runtime.
    OpenAPI therefore shows the un-versioned mount path while production
    URLs carry `/v1` (mirrors `tests/web/test_versioning.py::TestV1RouteAccessible`).
    """
    from breadmind.web.app import WebApp
    web = WebApp()
    client = TestClient(web.app)
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths", {})
    messenger_paths = [p for p in paths if p.startswith("/api/workspaces")]
    assert messenger_paths, (
        "messenger v1 router not mounted; expected /api/workspaces/* paths "
        "in OpenAPI"
    )


def test_messenger_exception_handler_installed():
    """A MessengerError raised inside the app must surface as the canonical
    error_to_response shape (HTTP 404 for NotFound, structured body)."""
    from breadmind.messenger.errors import NotFound
    from breadmind.web.app import WebApp
    web = WebApp()

    @web.app.get("/_test_messenger_err")
    async def _err():
        raise NotFound("widget", "x")

    client = TestClient(web.app)
    resp = client.get("/_test_messenger_err")
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 404
    assert body["code"] == "not_found"
    assert body["entity_kind"] == "widget"
    assert body["entity_id"] == "x"
