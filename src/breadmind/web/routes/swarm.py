"""Swarm management, skills CRUD, and performance routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["swarm"])


def setup_swarm_routes(r: APIRouter, app_state):
    """Register /api/swarm/*, /api/skills (CRUD), /api/performance/* routes."""

    # --- Swarm endpoints ---

    @r.post("/api/swarm/spawn")
    async def spawn_swarm(request: Request):
        if not app_state._swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        data = await request.json()
        result = await app_state._swarm_manager.spawn_swarm(
            goal=data.get("goal", ""),
            roles=data.get("roles"),
        )
        return {"status": "ok", "swarm_id": result.id}

    @r.get("/api/swarm/list")
    async def list_swarms():
        if not app_state._swarm_manager:
            return {"swarms": []}
        return {"swarms": app_state._swarm_manager.list_swarms()}

    @r.get("/api/swarm/{swarm_id}")
    async def get_swarm(swarm_id: str):
        if not app_state._swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        swarm = app_state._swarm_manager.get_swarm(swarm_id)
        if not swarm:
            return JSONResponse(status_code=404, content={"error": "Swarm not found"})
        return {"swarm": swarm}

    @r.get("/api/swarm/status")
    async def swarm_status():
        if not app_state._swarm_manager:
            return {"status": {"total": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0}}
        return {"status": app_state._swarm_manager.get_status()}

    @r.get("/api/swarm/roles")
    async def swarm_roles():
        if not app_state._swarm_manager:
            return {"roles": []}
        return {"roles": app_state._swarm_manager.get_available_roles()}

    @r.post("/api/swarm/roles")
    async def add_swarm_role(request: Request):
        if not app_state._swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        data = await request.json()
        name = data.get("name", "").strip().lower().replace(" ", "_")
        prompt = data.get("system_prompt", "")
        desc = data.get("description", "")
        if not name or not prompt:
            return JSONResponse(status_code=400, content={"error": "name and system_prompt required"})
        app_state._swarm_manager.add_role(name, prompt, desc)
        await app_state._persist_swarm_roles()
        return {"status": "ok", "role": name}

    @r.put("/api/swarm/roles/{role_name}")
    async def update_swarm_role(role_name: str, request: Request):
        if not app_state._swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        data = await request.json()
        app_state._swarm_manager.update_role(
            role_name,
            system_prompt=data.get("system_prompt", ""),
            description=data.get("description", ""),
        )
        await app_state._persist_swarm_roles()
        return {"status": "ok"}

    @r.delete("/api/swarm/roles/{role_name}")
    async def delete_swarm_role(role_name: str):
        if not app_state._swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        removed = app_state._swarm_manager.remove_role(role_name)
        if not removed:
            return JSONResponse(status_code=404, content={"error": "Role not found"})
        await app_state._persist_swarm_roles()
        return {"status": "ok"}

    # --- Skills endpoints ---

    @r.get("/api/skills")
    async def list_skills():
        if not app_state._skill_store:
            return []
        skills = await app_state._skill_store.list_skills()
        return [{"name": s.name, "description": s.description, "source": s.source,
                 "usage_count": s.usage_count, "trigger_keywords": s.trigger_keywords} for s in skills]

    @r.post("/api/skills")
    async def create_skill(request: Request):
        if not app_state._skill_store:
            return JSONResponse(status_code=503, content={"error": "Skill store not configured"})
        body = await request.json()
        skill = await app_state._skill_store.add_skill(
            name=body["name"], description=body["description"],
            prompt_template=body.get("prompt_template", ""),
            steps=body.get("steps", []),
            trigger_keywords=body.get("trigger_keywords", []),
            source="manual")
        await app_state._skill_store.flush_to_db()
        return {"name": skill.name, "status": "created"}

    @r.put("/api/skills/{name}")
    async def update_skill(name: str, request: Request):
        if not app_state._skill_store:
            return JSONResponse(status_code=503, content={"error": "Skill store not configured"})
        body = await request.json()
        await app_state._skill_store.update_skill(name, **body)
        await app_state._skill_store.flush_to_db()
        return {"name": name, "status": "updated"}

    @r.delete("/api/skills/{name}")
    async def delete_skill(name: str):
        if not app_state._skill_store:
            return JSONResponse(status_code=503, content={"error": "Skill store not configured"})
        removed = await app_state._skill_store.remove_skill(name)
        if removed:
            await app_state._skill_store.flush_to_db()
        return {"name": name, "removed": removed}

    # --- Performance endpoints ---

    @r.get("/api/performance")
    async def get_performance():
        if not app_state._performance_tracker:
            return {}
        all_stats = app_state._performance_tracker.get_all_stats()
        return {name: {"total_runs": s.total_runs, "success_rate": s.success_rate,
                        "avg_duration_ms": s.avg_duration_ms, "failures": s.failures}
                for name, s in all_stats.items()}

    @r.get("/api/performance/{role}")
    async def get_role_performance(role: str):
        if not app_state._performance_tracker:
            return JSONResponse(status_code=503, content={"error": "Performance tracker not configured"})
        stats = app_state._performance_tracker.get_role_stats(role)
        if not stats:
            return JSONResponse(status_code=404, content={"error": f"No stats for '{role}'"})
        return {"role": role, "total_runs": stats.total_runs,
                "success_rate": stats.success_rate, "avg_duration_ms": stats.avg_duration_ms,
                "successes": stats.successes, "failures": stats.failures,
                "feedback_count": len(stats.feedback_history)}
