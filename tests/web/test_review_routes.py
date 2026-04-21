"""Tests for KB review web routes (Task 16)."""
from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from breadmind.kb.review_queue import ReviewQueue
from breadmind.kb.types import ExtractedCandidate
from breadmind.web.routes.review import (
    get_current_slack_user,
    get_review_queue,
    router as review_router,
)


def _build_app(db, fake_slack_client, current_user: str | None = "U-LEAD") -> FastAPI:
    app = FastAPI()
    app.include_router(review_router, prefix="/api/review")
    app.dependency_overrides[get_review_queue] = lambda: ReviewQueue(db, fake_slack_client)
    app.dependency_overrides[get_current_slack_user] = lambda: current_user
    return app


def _client(app: FastAPI) -> AsyncClient:
    """AsyncClient avoids the cross-event-loop issue that TestClient causes
    with asyncpg pools created in the test's async fixtures.
    """
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _candidate(db, seeded_project, fake_slack_client) -> int:
    rq = ReviewQueue(db, fake_slack_client)
    return await rq.enqueue(
        ExtractedCandidate(
            proposed_title="t",
            proposed_body="b",
            proposed_category="howto",
            confidence=0.9,
            sources=[],
            original_user="U-AUTHOR",
            project_id=seeded_project,
        )
    )


async def test_list_pending_unauthorized_without_user(
    db, seeded_project, fake_slack_client,
):
    app = _build_app(db, fake_slack_client, current_user=None)
    async with _client(app) as c:
        r = await c.get(f"/api/review/pending?project_id={seeded_project}")
    assert r.status_code == 401


async def test_list_pending_returns_items(
    db, seeded_project, fake_slack_client,
):
    cid = await _candidate(db, seeded_project, fake_slack_client)
    app = _build_app(db, fake_slack_client)
    async with _client(app) as c:
        r = await c.get(f"/api/review/pending?project_id={seeded_project}")
    assert r.status_code == 200
    data = r.json()
    ids = [item["id"] for item in data["items"]]
    assert cid in ids


async def test_edit_updates_body(
    db, seeded_project, fake_slack_client,
):
    cid = await _candidate(db, seeded_project, fake_slack_client)
    app = _build_app(db, fake_slack_client)
    async with _client(app) as c:
        r = await c.post(f"/api/review/{cid}/edit", json={"body": "fixed body"})
    assert r.status_code == 200
    async with db.acquire() as conn:
        body = await conn.fetchval(
            "SELECT proposed_body FROM promotion_candidates WHERE id=$1", cid
        )
    assert body == "fixed body"


async def test_approve_via_web(
    db, seeded_project, fake_slack_client, monkeypatch,
):
    async def fake_embed(text: str):
        return [0.1] * 384

    from breadmind.kb import review_queue as rq_mod
    monkeypatch.setattr(rq_mod, "_embed_text", fake_embed)

    cid = await _candidate(db, seeded_project, fake_slack_client)
    app = _build_app(db, fake_slack_client)
    async with _client(app) as c:
        r = await c.post(f"/api/review/{cid}/approve")
    assert r.status_code == 200
    assert r.json()["knowledge_id"] > 0
