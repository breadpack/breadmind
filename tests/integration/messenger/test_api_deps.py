import pytest_asyncio
from fastapi import FastAPI, Depends
from httpx import AsyncClient, ASGITransport
from uuid import uuid4

from breadmind.messenger.api.v1 import install_exception_handlers
from breadmind.messenger.api.v1.deps import (
    get_current_user, get_workspace_context, CurrentUser, WorkspaceContext,
)
from breadmind.messenger.auth.paseto import encode_access_token

KEY = "00" * 32


def _build_app(db_pool):
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/me")
    async def me(claims: CurrentUser = Depends(get_current_user)):
        return {"user_id": str(claims.id), "role": claims.role}

    @app.get("/workspaces/{wid}/probe")
    async def probe(ctx: WorkspaceContext = Depends(get_workspace_context)):
        return {"workspace_id": str(ctx.workspace_id), "user_id": str(ctx.user.id)}

    app.state.db_pool = db_pool
    app.state.paseto_key_hex = KEY
    return app


async def test_get_current_user_success(db_pool, seed_workspace):
    wid, uid = seed_workspace
    app = _build_app(db_pool)
    token = encode_access_token(KEY, workspace_id=wid, user_id=uid, role="owner", ttl_min=30)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user_id"] == str(uid)


async def test_missing_token_401(db_pool):
    app = _build_app(db_pool)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/me")
    assert r.status_code == 401


async def test_invalid_token_401(db_pool):
    app = _build_app(db_pool)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


async def test_workspace_context_mismatch_403(db_pool, seed_workspace):
    wid, uid = seed_workspace
    app = _build_app(db_pool)
    token = encode_access_token(KEY, workspace_id=wid, user_id=uid, role="owner", ttl_min=30)
    other_wid = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/workspaces/{other_wid}/probe",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 403
