import pytest
import pytest_asyncio
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
