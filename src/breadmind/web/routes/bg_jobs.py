"""Background job REST API routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bg-jobs"])


def _serialize_job(job: dict) -> dict:
    """Convert UUID/datetime fields to JSON-serializable strings."""
    out = {}
    for k, v in job.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "hex"):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def setup_bg_job_routes(r, app_state):
    """Register background job routes."""

    def _mgr():
        return getattr(app_state, "_bg_job_manager", None)

    @r.get("/api/bg-jobs")
    async def list_jobs(status: str | None = None):
        mgr = _mgr()
        if not mgr:
            return JSONResponse(503, {"error": "Background jobs not available"})
        jobs = await mgr.list_jobs(status=status)
        return {"jobs": [_serialize_job(j) for j in jobs]}

    @r.get("/api/bg-jobs/{job_id}")
    async def get_job(job_id: str):
        mgr = _mgr()
        if not mgr:
            return JSONResponse(503, {"error": "Background jobs not available"})
        job = await mgr.get_job(job_id)
        if not job:
            return JSONResponse(404, {"error": "Job not found"})
        return {"job": _serialize_job(job)}

    @r.post("/api/bg-jobs/{job_id}/pause")
    async def pause_job(job_id: str):
        mgr = _mgr()
        if not mgr:
            return JSONResponse(503, {"error": "Background jobs not available"})
        if not await mgr.pause_job(job_id):
            return JSONResponse(400, {"error": "Cannot pause this job"})
        return {"success": True}

    @r.post("/api/bg-jobs/{job_id}/resume")
    async def resume_job(job_id: str):
        mgr = _mgr()
        if not mgr:
            return JSONResponse(503, {"error": "Background jobs not available"})
        if not await mgr.resume_job(job_id):
            return JSONResponse(400, {"error": "Cannot resume this job"})
        return {"success": True}

    @r.post("/api/bg-jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        mgr = _mgr()
        if not mgr:
            return JSONResponse(503, {"error": "Background jobs not available"})
        if not await mgr.cancel_job(job_id):
            return JSONResponse(400, {"error": "Cannot cancel this job"})
        return {"success": True}

    @r.delete("/api/bg-jobs/{job_id}")
    async def delete_job(job_id: str):
        mgr = _mgr()
        if not mgr:
            return JSONResponse(503, {"error": "Background jobs not available"})
        if not await mgr.delete_job(job_id):
            return JSONResponse(400, {"error": "Cannot delete this job"})
        return {"success": True}
