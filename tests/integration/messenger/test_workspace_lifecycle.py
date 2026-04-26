import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_workspace_user_insert_round_trip(test_db):
    workspace_id = uuid4()
    # Use a uuid-based slug so repeated test runs don't collide on the UNIQUE constraint.
    slug = f"acme-{workspace_id.hex[:8]}"
    await test_db.execute(
        "INSERT INTO org_projects (id, name, slug, plan) VALUES ($1, $2, $3, 'free')",
        workspace_id, "Acme Studio", slug,
    )
    user_id = uuid4()
    await test_db.execute(
        """INSERT INTO workspace_users
              (id, workspace_id, email, kind, display_name, role)
           VALUES ($1, $2, $3, 'human', $4, 'member')""",
        user_id, workspace_id, "alice@acme.com", "alice",
    )
    row = await test_db.fetchrow(
        "SELECT email, kind, role, locale FROM workspace_users WHERE id = $1",
        user_id,
    )
    assert row["email"] == "alice@acme.com"
    assert row["kind"] == "human"
    assert row["role"] == "member"
    assert row["locale"] == "ko"  # default


@pytest.mark.asyncio
async def test_workspace_user_email_unique_per_workspace(test_db):
    wid = uuid4()
    # Use a uuid-based slug so repeated test runs don't collide on the UNIQUE constraint.
    slug = f"w-{wid.hex[:8]}"
    await test_db.execute(
        "INSERT INTO org_projects (id, name, slug, plan) VALUES ($1, 'W', $2, 'free')",
        wid, slug,
    )
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name) "
        "VALUES (gen_random_uuid(), $1, 'bob@x.com', 'human', 'bob')",
        wid,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name) "
            "VALUES (gen_random_uuid(), $1, 'bob@x.com', 'human', 'bob2')",
            wid,
        )
