"""Swarm management, skills CRUD, and performance routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import (
    get_app_state, get_performance_tracker, get_skill_store, get_swarm_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["swarm"])


def setup_swarm_routes(r: APIRouter, app_state):
    """Register /api/swarm/*, /api/skills (CRUD), /api/performance/* routes."""

    # --- Swarm endpoints ---

    @r.post("/api/swarm/spawn")
    async def spawn_swarm(request: Request, swarm_manager=Depends(get_swarm_manager)):
        if not swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        data = await request.json()
        result = await swarm_manager.spawn_swarm(
            goal=data.get("goal", ""),
            roles=data.get("roles"),
        )
        return {"status": "ok", "swarm_id": result.id}

    @r.get("/api/swarm/list")
    async def list_swarms(swarm_manager=Depends(get_swarm_manager)):
        if not swarm_manager:
            return {"swarms": []}
        return {"swarms": swarm_manager.list_swarms()}

    @r.get("/api/swarm/{swarm_id}")
    async def get_swarm(swarm_id: str, swarm_manager=Depends(get_swarm_manager)):
        if not swarm_manager:
            return JSONResponse(status_code=503, content={"error": "Swarm manager not configured"})
        swarm = swarm_manager.get_swarm(swarm_id)
        if not swarm:
            return JSONResponse(status_code=404, content={"error": "Swarm not found"})
        return {"swarm": swarm}

    @r.get("/api/swarm/status")
    async def swarm_status(swarm_manager=Depends(get_swarm_manager)):
        if not swarm_manager:
            return {"status": {"total": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0}}
        return {"status": swarm_manager.get_status()}

    @r.get("/api/swarm/roles")
    async def swarm_roles(app=Depends(get_app_state)):
        role_registry = app._container.get("role_registry") if app._container else None
        if not role_registry:
            return {"roles": []}
        return {"roles": [r.to_dict() for r in role_registry.list_roles()]}

    @r.post("/api/swarm/roles")
    async def add_swarm_role(request: Request, app=Depends(get_app_state)):
        role_registry = app._container.get("role_registry") if app._container else None
        if not role_registry:
            return JSONResponse(status_code=503, content={"error": "Role registry not available"})
        data = await request.json()
        name = data.get("name", "").strip().lower().replace(" ", "_")
        if not name or not data.get("system_prompt"):
            return JSONResponse(status_code=400, content={"error": "name and system_prompt required"})
        from breadmind.core.role_registry import RoleDefinition
        role = RoleDefinition(
            name=name,
            domain=data.get("domain", "general"),
            task_type=data.get("task_type", "general"),
            system_prompt=data["system_prompt"],
            description=data.get("description", ""),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            tool_mode=data.get("tool_mode", "whitelist"),
            tools=data.get("tools", []),
            persistent=data.get("persistent", True),
            created_by="user",
            max_turns=data.get("max_turns", 5),
        )
        await role_registry.register(role, db=app._db)
        return {"status": "ok", "role": name}

    @r.put("/api/swarm/roles/{role_name}")
    async def update_swarm_role(role_name: str, request: Request, app=Depends(get_app_state)):
        role_registry = app._container.get("role_registry") if app._container else None
        if not role_registry:
            return JSONResponse(status_code=503, content={"error": "Role registry not available"})
        existing = role_registry.get(role_name)
        if not existing:
            return JSONResponse(status_code=404, content={"error": "Role not found"})
        data = await request.json()
        from breadmind.core.role_registry import RoleDefinition
        updated = RoleDefinition(
            name=role_name,
            domain=data.get("domain", existing.domain),
            task_type=data.get("task_type", existing.task_type),
            system_prompt=data.get("system_prompt", existing.system_prompt),
            description=data.get("description", existing.description),
            provider=data.get("provider", existing.provider),
            model=data.get("model", existing.model),
            tool_mode=data.get("tool_mode", existing.tool_mode),
            tools=data.get("tools", existing.tools),
            persistent=data.get("persistent", existing.persistent),
            created_by=existing.created_by,
            max_turns=data.get("max_turns", existing.max_turns),
        )
        await role_registry.register(updated, db=app._db)
        return {"status": "ok"}

    @r.delete("/api/swarm/roles/{role_name}")
    async def delete_swarm_role(role_name: str, app=Depends(get_app_state)):
        role_registry = app._container.get("role_registry") if app._container else None
        if not role_registry:
            return JSONResponse(status_code=503, content={"error": "Role registry not available"})
        removed = await role_registry.remove(role_name, db=app._db)
        if not removed:
            return JSONResponse(status_code=404, content={"error": "Role not found"})
        return {"status": "ok"}

    # --- Skills endpoints ---

    @r.get("/api/skills")
    async def list_skills(skill_store=Depends(get_skill_store)):
        if not skill_store:
            return []
        skills = await skill_store.list_skills()
        return [{"name": s.name, "description": s.description, "source": s.source,
                 "usage_count": s.usage_count, "trigger_keywords": s.trigger_keywords} for s in skills]

    @r.post("/api/skills")
    async def create_skill(request: Request, skill_store=Depends(get_skill_store)):
        if not skill_store:
            return JSONResponse(status_code=503, content={"error": "Skill store not configured"})
        body = await request.json()
        skill = await skill_store.add_skill(
            name=body["name"], description=body["description"],
            prompt_template=body.get("prompt_template", ""),
            steps=body.get("steps", []),
            trigger_keywords=body.get("trigger_keywords", []),
            source="manual")
        await skill_store.flush_to_db()
        return {"name": skill.name, "status": "created"}

    @r.put("/api/skills/{name}")
    async def update_skill(name: str, request: Request, skill_store=Depends(get_skill_store)):
        if not skill_store:
            return JSONResponse(status_code=503, content={"error": "Skill store not configured"})
        body = await request.json()
        await skill_store.update_skill(name, **body)
        await skill_store.flush_to_db()
        return {"name": name, "status": "updated"}

    @r.delete("/api/skills/{name}")
    async def delete_skill(name: str, skill_store=Depends(get_skill_store)):
        if not skill_store:
            return JSONResponse(status_code=503, content={"error": "Skill store not configured"})
        removed = await skill_store.remove_skill(name)
        if removed:
            await skill_store.flush_to_db()
        return {"name": name, "removed": removed}

    # --- Performance endpoints ---

    @r.get("/api/performance")
    async def get_performance(performance_tracker=Depends(get_performance_tracker)):
        if not performance_tracker:
            return {}
        all_stats = performance_tracker.get_all_stats()
        return {name: {"total_runs": s.total_runs, "success_rate": s.success_rate,
                        "avg_duration_ms": s.avg_duration_ms, "failures": s.failures}
                for name, s in all_stats.items()}

    @r.get("/api/performance/{role}")
    async def get_role_performance(role: str, performance_tracker=Depends(get_performance_tracker)):
        if not performance_tracker:
            return JSONResponse(status_code=503, content={"error": "Performance tracker not configured"})
        stats = performance_tracker.get_role_stats(role)
        if not stats:
            return JSONResponse(status_code=404, content={"error": f"No stats for '{role}'"})
        return {"role": role, "total_runs": stats.total_runs,
                "success_rate": stats.success_rate, "avg_duration_ms": stats.avg_duration_ms,
                "successes": stats.successes, "failures": stats.failures,
                "feedback_count": len(stats.feedback_history)}
