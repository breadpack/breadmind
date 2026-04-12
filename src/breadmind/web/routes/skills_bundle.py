from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from breadmind.skills.checklist import get_checklist_tracker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["skills-bundle"])


class InstallBundleIn(BaseModel):
    path: str


class StartChecklistIn(BaseModel):
    session_id: str
    skill_name: str
    steps: list[str]


class AdvanceChecklistIn(BaseModel):
    session_id: str
    skill_name: str


def _get_store(request: Request):
    store = getattr(request.app.state, "skill_store", None)
    if store is None:
        raise HTTPException(500, "SkillStore not configured")
    return store


@router.post("/api/skills/bundle/install")
async def install_bundle(body: InstallBundleIn, request: Request):
    store = _get_store(request)
    path = Path(body.path)
    if not path.is_dir():
        raise HTTPException(400, f"Not a directory: {path}")
    try:
        skill = await store.install_bundle(path)
    except Exception as e:
        raise HTTPException(400, f"Bundle install failed: {e}")
    return {
        "status": "ok",
        "skill": {
            "name": skill.name,
            "description": skill.description,
            "priority": skill.priority,
            "depends_on": skill.depends_on,
            "tags": skill.tags,
            "reference_markers": skill.reference_markers,
            "bundle_path": skill.bundle_path,
        },
    }


@router.get("/api/skills/{name}/references")
async def list_references(name: str, request: Request):
    store = _get_store(request)
    if hasattr(store, "get_skill"):
        skill = await store.get_skill(name)
    else:
        skill = store._skills.get(name)
    if skill is None:
        raise HTTPException(404, f"Skill not found: {name}")
    return {"references": list(getattr(skill, "reference_markers", []))}


@router.post("/api/skills/checklist/start")
async def start_checklist(body: StartChecklistIn):
    state = get_checklist_tracker().start(
        body.session_id, body.skill_name, steps=body.steps,
    )
    return {"status": "ok", "state": state.to_dict()}


@router.post("/api/skills/checklist/advance")
async def advance_checklist(body: AdvanceChecklistIn):
    state = get_checklist_tracker().advance(body.session_id, body.skill_name)
    if state is None:
        raise HTTPException(404, "No active checklist")
    return {"status": "ok", "state": state.to_dict()}


@router.get("/api/skills/checklist/summary")
async def checklist_summary(session_id: str):
    summary = get_checklist_tracker().summary(session_id)
    return {"summary": summary}
