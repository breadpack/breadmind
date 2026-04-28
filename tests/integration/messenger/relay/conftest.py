import os
import pathlib
import subprocess
import time
from dataclasses import dataclass
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio

from breadmind.messenger.auth.session import create_session
from breadmind.messenger.service.workspace_service import create_workspace


PASETO_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PG_DSN = "postgres://breadmind:breadmind@localhost:5434/breadmind"


@dataclass
class TestUser:
    id: str
    token: str
    email: str
    workspace_id: str


@pytest.fixture(scope="session")
def compose_stack():
    if os.getenv("RELAY_TESTS_USE_RUNNING_STACK") == "1":
        yield "http://localhost:8080", "ws://localhost:8090"
        return
    repo = pathlib.Path(__file__).resolve().parents[4]
    file = repo / "docker-compose.test.yml"
    subprocess.check_call(["docker", "compose", "-f", str(file), "up", "-d", "--build"])
    try:
        for _ in range(60):
            try:
                if httpx.get("http://localhost:8090/healthz", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("relay never became healthy")
        yield "http://localhost:8080", "ws://localhost:8090"
    finally:
        subprocess.check_call(["docker", "compose", "-f", str(file), "down", "-v"])


async def _seed_user(workspace_id, email, role="member"):
    pool = await asyncpg.create_pool(PG_DSN)
    async with pool.acquire() as conn:
        uid = uuid4()
        await conn.execute(
            "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role)"
            " VALUES ($1,$2,$3,'human',$4,$5)",
            uid, workspace_id, email, email.split("@")[0], role,
        )
        sess = await create_session(
            conn, PASETO_KEY, user_id=uid, workspace_id=workspace_id,
            access_ttl_min=60, refresh_ttl_days=30,
        )
    await pool.close()
    return TestUser(id=str(uid), token=sess.access_token, email=email,
                    workspace_id=str(workspace_id))


@pytest_asyncio.fixture
async def workspace_owner(compose_stack):
    pool = await asyncpg.create_pool(PG_DSN)
    async with pool.acquire() as conn:
        ws = await create_workspace(conn, name="Relay Tests",
                                     slug=f"relay-{uuid4().hex[:8]}", created_by=None)
    await pool.close()
    return await _seed_user(ws.id, f"owner-{uuid4().hex[:8]}@test.local", role="owner")


@pytest_asyncio.fixture
async def two_users_one_channel(compose_stack, workspace_owner):
    api, _ = compose_stack
    user_b = await _seed_user(
        workspace_owner.workspace_id, f"b-{uuid4().hex[:8]}@test.local"
    )
    async with httpx.AsyncClient(
        base_url=api,
        headers={"Authorization": f"Bearer {workspace_owner.token}"},
    ) as hc:
        ch_resp = await hc.post(
            f"/api/v1/workspaces/{workspace_owner.workspace_id}/channels",
            json={"kind": "public", "name": f"gen-{uuid4().hex[:8]}"},
        )
        ch = ch_resp.json()
        await hc.post(
            f"/api/v1/channels/{ch['id']}/members", json={"user_id": user_b.id}
        )
    return workspace_owner, user_b, ch["id"]


@pytest_asyncio.fixture
async def user_with_channel(compose_stack, workspace_owner):
    api, _ = compose_stack
    async with httpx.AsyncClient(
        base_url=api,
        headers={"Authorization": f"Bearer {workspace_owner.token}"},
    ) as hc:
        ch_resp = await hc.post(
            f"/api/v1/workspaces/{workspace_owner.workspace_id}/channels",
            json={"kind": "public", "name": f"solo-{uuid4().hex[:8]}"},
        )
        ch = ch_resp.json()
    return workspace_owner, ch["id"]


@pytest_asyncio.fixture
async def private_channel_setup(compose_stack, workspace_owner):
    api, _ = compose_stack
    intruder = await _seed_user(
        workspace_owner.workspace_id, f"intruder-{uuid4().hex[:8]}@test.local"
    )
    async with httpx.AsyncClient(
        base_url=api,
        headers={"Authorization": f"Bearer {workspace_owner.token}"},
    ) as hc:
        ch_resp = await hc.post(
            f"/api/v1/workspaces/{workspace_owner.workspace_id}/channels",
            json={"kind": "private", "name": f"sec-{uuid4().hex[:8]}"},
        )
        ch = ch_resp.json()
    return intruder, ch["id"]


@pytest_asyncio.fixture
async def valid_user_token(workspace_owner):
    return workspace_owner.token
