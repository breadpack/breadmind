"""Web routes for long-running coding job monitoring.

Provides REST API and WebSocket integration for tracking
code_delegate long_running jobs in real-time.

Task 13 tightened authz:
- ``GET /api/coding-jobs`` supports ``mine`` / ``status`` / ``limit`` / ``since_days``
  filters. Non-admin callers default to ``mine=1`` and get 403 if they try
  to request the all-jobs view.
- ``GET /api/coding-jobs/active`` is filtered to the caller's jobs unless
  they are an admin.
- ``GET /api/coding-jobs/{job_id}`` returns 404 for non-owner non-admin
  callers (existence hiding) rather than 403, so a probe cannot confirm
  whether a given ``job_id`` exists.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from breadmind.web.deps import CurrentUser, get_current_user

logger = logging.getLogger(__name__)


def register_coding_job_routes(app: Any) -> None:
    """Register coding job monitoring routes on the FastAPI app."""

    @app.get("/api/coding-jobs")
    async def list_coding_jobs(
        status: str | None = None,
        mine: int | None = None,
        limit: int = 100,
        since_days: int = 30,
        current: CurrentUser = Depends(get_current_user),
    ):
        """List coding jobs, filtered by caller identity.

        Query params:
            status: optional JobStatus value to filter by.
            mine: 1=only caller's jobs, 0=all (admin-only), unset=auto
                  (admins see all, non-admins see their own).
            limit: cap on returned rows (1..500, default 100).
            since_days: only include jobs started within the last N days.
        """
        from breadmind.coding.job_tracker import JobTracker

        tracker = JobTracker.get_instance()

        if mine is None:
            mine_effective = 0 if current.is_admin else 1
        else:
            mine_effective = int(mine)

        if mine_effective:
            jobs = [
                j for j in tracker.list_jobs(status=status)
                if j.user == current.username
            ]
        else:
            if not current.is_admin:
                raise HTTPException(403, "admin only for all-jobs view")
            jobs = tracker.list_jobs(status=status)

        # since_days filter — keep jobs that started within the window.
        if since_days > 0:
            import time
            cutoff = time.time() - (since_days * 86400)
            jobs = [j for j in jobs if j.started_at >= cutoff]

        # Clamp limit to [1, 500] to prevent absurd pulls.
        capped = max(1, min(int(limit), 500))
        jobs = jobs[:capped]
        return JSONResponse([j.to_dict() for j in jobs])

    @app.get("/api/coding-jobs/active")
    async def list_active_jobs(
        current: CurrentUser = Depends(get_current_user),
    ):
        """List only active (running/pending) coding jobs.

        Filtered to the caller's jobs unless the caller is an admin.
        """
        from breadmind.coding.job_tracker import JobTracker

        tracker = JobTracker.get_instance()
        jobs = tracker.get_active_jobs()
        if not current.is_admin:
            jobs = [j for j in jobs if j.user == current.username]
        return JSONResponse([j.to_dict() for j in jobs])

    @app.get("/api/coding-jobs/{job_id}")
    async def get_coding_job(
        job_id: str,
        current: CurrentUser = Depends(get_current_user),
    ):
        """Get details of a specific coding job.

        Returns 404 both when the job is missing and when the caller is
        neither the owner nor an admin — existence hiding.
        """
        from breadmind.coding.job_tracker import JobTracker

        tracker = JobTracker.get_instance()
        job = tracker.get_job(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        if not current.is_admin and job.user != current.username:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        return JSONResponse(job.to_dict())

    @app.post("/api/coding-jobs/{job_id}/cancel")
    async def cancel_coding_job(
        request: Request,
        job_id: str,
        current: CurrentUser = Depends(get_current_user),
    ):
        """Cancel a running coding job.

        Mirrors the detail endpoint's existence-hiding: non-owner non-admin
        callers get 404 rather than 403.
        """
        from breadmind.coding.job_tracker import JobTracker

        tracker = JobTracker.get_instance()
        job = tracker.get_job(job_id)
        if not job:
            return JSONResponse(
                {"error": "Job not found"}, status_code=404
            )
        if not current.is_admin and job.user != current.username:
            return JSONResponse(
                {"error": "Job not found"}, status_code=404
            )

        cancelled = tracker.cancel_job(job_id)
        if not cancelled:
            return JSONResponse(
                {"error": "Job not found or already finished"},
                status_code=400,
            )
        return JSONResponse({"ok": True, "job_id": job_id})

    # ── WebSocket push via EventBus ──────────────────────────────────────
    # Register a listener that forwards job events to all WebSocket clients
    _setup_websocket_push(app)


def _setup_websocket_push(app: Any) -> None:
    """Wire JobTracker events to WebSocket broadcast."""
    from breadmind.coding.job_tracker import JobTracker

    tracker = JobTracker.get_instance()

    async def _on_job_event(event_type: str, job: Any) -> None:
        """Forward job events to WebSocket clients."""
        try:
            if hasattr(app, "broadcast_event"):
                await app.broadcast_event({
                    "type": f"coding_job_{event_type}",
                    "data": job.to_dict(),
                })
        except Exception as e:
            logger.debug("WebSocket broadcast failed: %s", e)

    tracker.add_listener(_on_job_event)
    logger.info("Coding job WebSocket push registered")
