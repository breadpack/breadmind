import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport
from uuid import uuid4


@pytest_asyncio.fixture
async def db_pool(test_db):
    """Expose the underlying asyncpg.Pool from test_db for FastAPI deps testing."""
    return test_db._pool


@pytest_asyncio.fixture
async def seed_workspace(test_db):
    wid = uuid4()
    owner_id = uuid4()
    slug = f"test-{uuid4().hex[:8]}"
    await test_db.execute(
        "INSERT INTO org_projects (id, name, slug, plan) VALUES ($1, 'Test', $2, 'free')",
        wid, slug,
    )
    await test_db.execute(
        """INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role)
           VALUES ($1, $2, $3, 'human', 'Owner', 'owner')""",
        owner_id, wid, f"owner-{uuid4().hex[:8]}@test.com",
    )
    return wid, owner_id


@pytest_asyncio.fixture
async def seed_channel(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    from uuid import uuid4
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) "
        "VALUES ($1, $2, 'public', $3)", cid, wid, f"general-{cid.hex[:8]}",
    )
    await test_db.execute(
        "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)",
        cid, owner_id,
    )
    return wid, cid, owner_id


@pytest.fixture
def fake_smtp():
    sent = []

    class FakeSmtp:
        def send(self, *, to: str, subject: str, body: str) -> None:
            sent.append({"to": to, "subject": subject, "body": body})

    smtp = FakeSmtp()
    smtp.sent = sent
    return smtp


@pytest_asyncio.fixture
async def redis_client():
    import fakeredis.aioredis
    r = fakeredis.aioredis.FakeRedis()
    try:
        yield r
    finally:
        await r.flushall()
        await r.aclose()


@pytest_asyncio.fixture
async def messenger_app(db_pool, redis_client):
    """FastAPI app with full /api/v1 router mounted, ready for httpx.AsyncClient."""
    from fastapi import FastAPI
    from breadmind.messenger.api.v1 import router, install_exception_handlers
    app = FastAPI()
    install_exception_handlers(app)
    app.state.db_pool = db_pool
    app.state.redis = redis_client
    app.state.paseto_key_hex = "00" * 32
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def messenger_app_client(messenger_app):
    """httpx.AsyncClient wired to the messenger app via ASGITransport."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=messenger_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def owner_workspace_id(seed_workspace):
    wid, _ = seed_workspace
    return wid


@pytest.fixture
def owner_token(seed_workspace):
    from breadmind.messenger.auth.paseto import encode_access_token
    wid, uid = seed_workspace
    return encode_access_token("00" * 32, workspace_id=wid, user_id=uid, role="owner", ttl_min=30)


@pytest_asyncio.fixture
async def member_token(test_db, seed_workspace):
    from breadmind.messenger.auth.paseto import encode_access_token
    wid, _ = seed_workspace
    uid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'M', 'member')",
        uid, wid, f"m-{suffix}@x.com",
    )
    return encode_access_token("00" * 32, workspace_id=wid, user_id=uid, role="member", ttl_min=30)
