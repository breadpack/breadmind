from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from breadmind.core.skill_store import SkillStore
from breadmind.skills.checklist import get_checklist_tracker
from breadmind.web.routes.skills_bundle import router as bundle_router


FIXTURE = Path(__file__).parent / "fixtures" / "sample_bundle"


@pytest.fixture
def app_with_skills():
    app = FastAPI()
    app.state.skill_store = SkillStore(db=None, tracker=None)
    app.include_router(bundle_router)
    return app


def test_install_bundle_endpoint(app_with_skills):
    client = TestClient(app_with_skills)
    resp = client.post(
        "/api/skills/bundle/install", json={"path": str(FIXTURE)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skill"]["name"] == "sample-skill"
    assert data["skill"]["priority"] == 10


def test_list_references_endpoint(app_with_skills):
    client = TestClient(app_with_skills)
    client.post("/api/skills/bundle/install", json={"path": str(FIXTURE)})
    resp = client.get("/api/skills/sample-skill/references")
    assert resp.status_code == 200
    refs = resp.json()["references"]
    assert "references/overview.md" in refs
    assert "references/detail.md" in refs


def test_checklist_lifecycle_via_routes(app_with_skills):
    # Reset shared tracker for isolation
    get_checklist_tracker()._state.clear()
    client = TestClient(app_with_skills)
    resp = client.post(
        "/api/skills/checklist/start",
        json={"session_id": "s1", "skill_name": "refactor", "steps": ["a", "b"]},
    )
    assert resp.status_code == 200
    assert resp.json()["state"]["current_step"] == "a"

    resp = client.post(
        "/api/skills/checklist/advance",
        json={"session_id": "s1", "skill_name": "refactor"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"]["completed_count"] == 1

    resp = client.get("/api/skills/checklist/summary?session_id=s1")
    assert resp.status_code == 200
    assert len(resp.json()["summary"]) == 1
