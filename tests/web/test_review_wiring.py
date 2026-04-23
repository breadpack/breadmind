"""Production wiring tests for KB review routes.

``review.get_review_queue`` was a sentinel that raised 500 until Task 17
wired it. These tests assert that with only the production wiring in
place (no test-level ``dependency_overrides[get_review_queue]`` and no
stub store), the review endpoints behave correctly end-to-end against
the real ``Database`` wrapper:

1. unauthenticated → 401 (not 500)
2. authenticated + empty queue → 200 with empty items list
"""
from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from breadmind.web.routes.review import (
    get_current_slack_user,
    router as review_router,
)


class _AppState:
    """Minimal shim matching ``dependencies.get_db`` expectations."""

    def __init__(self, db):
        self._db = db


def _build_prod_app(db) -> FastAPI:
    """Mount the review router exactly like ``web.app.create_app`` does,
    WITHOUT installing any ``get_review_queue`` override. This proves
    the default (production) wiring is sufficient for the routes to work.
    """
    app = FastAPI()
    app.include_router(review_router, prefix="/api/review")
    app.state.app_state = _AppState(db)
    return app


async def test_production_wiring_returns_401_without_session(db, seeded_project):
    """Unauthenticated request must return 401, not 500.

    Before wiring: ``get_review_queue`` raises 500 regardless of auth
    state, so the 401 branch in ``_require_user`` was unreachable.
    After wiring: the queue is constructed, auth runs, missing session
    yields 401.
    """
    app = _build_prod_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as c:
        r = await c.get(f"/api/review/pending?project_id={seeded_project}")
    assert r.status_code == 401


async def test_production_wiring_authenticated_lists_empty_queue(
    db, seeded_project,
):
    """Authenticated request with no pending candidates must return an
    empty ``items`` list — proves ReviewQueue.list_pending() actually
    runs against the real Database wrapper end-to-end.
    """
    app = _build_prod_app(db)
    app.dependency_overrides[get_current_slack_user] = lambda: "U-LEAD"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as c:
        r = await c.get(f"/api/review/pending?project_id={seeded_project}")
    assert r.status_code == 200
    assert r.json() == {"items": []}
