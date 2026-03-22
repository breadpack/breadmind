"""Web routes for long-running coding job monitoring.

Provides REST API and WebSocket integration for tracking
code_delegate long_running jobs in real-time.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def register_coding_job_routes(app: Any) -> None:
    """Register coding job monitoring routes on the FastAPI app."""

    @app.get("/api/coding-jobs")
    async def list_coding_jobs(request: Request, status: str | None = None):
        """List all coding jobs, optionally filtered by status."""
        from breadmind.coding.job_tracker import JobTracker
        tracker = JobTracker.get_instance()
        jobs = tracker.list_jobs(status=status)
        return JSONResponse([j.to_dict() for j in jobs])

    @app.get("/api/coding-jobs/active")
    async def list_active_jobs(request: Request):
        """List only active (running/pending) coding jobs."""
        from breadmind.coding.job_tracker import JobTracker
        tracker = JobTracker.get_instance()
        jobs = tracker.get_active_jobs()
        return JSONResponse([j.to_dict() for j in jobs])

    @app.get("/api/coding-jobs/{job_id}")
    async def get_coding_job(request: Request, job_id: str):
        """Get details of a specific coding job."""
        from breadmind.coding.job_tracker import JobTracker
        tracker = JobTracker.get_instance()
        job = tracker.get_job(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)
        return JSONResponse(job.to_dict())

    @app.post("/api/coding-jobs/{job_id}/cancel")
    async def cancel_coding_job(request: Request, job_id: str):
        """Cancel a running coding job."""
        from breadmind.coding.job_tracker import JobTracker
        tracker = JobTracker.get_instance()
        cancelled = tracker.cancel_job(job_id)
        if not cancelled:
            return JSONResponse({"error": "Job not found or already finished"}, status_code=400)
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
