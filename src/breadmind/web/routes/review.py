"""Web review UI routes for KB promotion candidates.

Auth: Slack OAuth — we rely on an upstream middleware / session cookie to
populate the current Slack user; tests override the dependency.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from breadmind.kb.review_queue import ReviewQueue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["kb-review"])


def get_current_slack_user(request: Request) -> str | None:
    """Extract Slack user id from session/cookie.

    Production: populated by Slack OAuth middleware into
    ``request.session['slack_user']``. Returns None if unauthenticated.
    Tests override this dependency.
    """
    try:
        session = request.scope.get("session") or {}
    except Exception:  # noqa: BLE001
        session = {}
    if not isinstance(session, dict):
        return None
    return session.get("slack_user")


def get_review_queue() -> ReviewQueue:  # pragma: no cover
    """Production wiring of ReviewQueue. Tests override this dependency
    before any request executes, so this body is never reached in tests.

    In production, wire a concrete ``ReviewQueue(db, slack_client)`` via
    a startup event hook or by overriding this dependency at app creation
    time. Task 17 is responsible for the production wiring.
    """
    raise HTTPException(
        status_code=500,
        detail="ReviewQueue not wired; dependency must be provided",
    )


def _require_user(user: str | None) -> str:
    if not user:
        raise HTTPException(status_code=401, detail="slack login required")
    return user


@router.get("/pending")
async def list_pending(
    project_id: UUID,
    limit: int = 20,
    user: str | None = Depends(get_current_slack_user),
    queue: ReviewQueue = Depends(get_review_queue),
):
    _require_user(user)
    items = await queue.list_pending(project_id, limit=limit)
    return {
        "items": [
            {
                "id": c.id,
                "title": c.proposed_title,
                "body": c.proposed_body,
                "category": c.proposed_category,
                "confidence": c.confidence,
                "status": c.status,
                "sensitive_flag": c.sensitive_flag,
                "original_user": c.original_user,
            }
            for c in items
        ]
    }


@router.post("/{candidate_id}/edit")
async def edit_candidate(
    candidate_id: int,
    request: Request,
    user: str | None = Depends(get_current_slack_user),
    queue: ReviewQueue = Depends(get_review_queue),
):
    reviewer = _require_user(user)
    payload = await request.json()
    body = str(payload.get("body", "")).strip()
    if not body:
        raise HTTPException(status_code=400, detail="body is required")
    await queue.needs_edit(candidate_id, reviewer=reviewer, new_body=body)
    return {"status": "ok"}


@router.post("/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: int,
    user: str | None = Depends(get_current_slack_user),
    queue: ReviewQueue = Depends(get_review_queue),
):
    reviewer = _require_user(user)
    try:
        kid = await queue.approve(candidate_id, reviewer=reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"knowledge_id": kid, "status": "approved"}


@router.post("/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: int,
    request: Request,
    user: str | None = Depends(get_current_slack_user),
    queue: ReviewQueue = Depends(get_review_queue),
):
    reviewer = _require_user(user)
    payload = await request.json()
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=400, detail="reason is required")
    await queue.reject(candidate_id, reviewer=reviewer, reason=reason)
    return {"status": "rejected"}
