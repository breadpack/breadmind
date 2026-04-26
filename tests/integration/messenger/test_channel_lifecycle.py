import pytest
from uuid import uuid4


async def test_channel_public_round_trip(test_db, seed_workspace):
    wid, owner_id = seed_workspace  # fixture creates org_project + 1 owner
    cid = uuid4()
    await test_db.execute(
        """INSERT INTO channels (id, workspace_id, kind, name, created_by)
           VALUES ($1, $2, 'public', 'general', $3)""",
        cid, wid, owner_id,
    )
    row = await test_db.fetchrow("SELECT kind, name, posting_policy FROM channels WHERE id = $1", cid)
    assert row["kind"] == "public"
    assert row["name"] == "general"
    assert row["posting_policy"] == "all"


async def test_channel_dm_must_have_null_name(test_db, seed_workspace):
    wid, _ = seed_workspace
    with pytest.raises(Exception, match="violates check constraint"):
        await test_db.execute(
            "INSERT INTO channels (id, workspace_id, kind, name) "
            "VALUES (gen_random_uuid(), $1, 'dm', 'should_be_null')",
            wid,
        )


async def test_channel_public_unique_name(test_db, seed_workspace):
    wid, _ = seed_workspace
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) "
        "VALUES (gen_random_uuid(), $1, 'public', 'duplicate')", wid,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO channels (id, workspace_id, kind, name) "
            "VALUES (gen_random_uuid(), $1, 'public', 'duplicate')", wid,
        )


async def test_channel_member_pk(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    cid = uuid4()
    await test_db.execute(
        "INSERT INTO channels (id, workspace_id, kind, name) VALUES ($1, $2, 'public', 'g')",
        cid, wid,
    )
    await test_db.execute(
        "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)",
        cid, owner_id,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO channel_members (channel_id, user_id) VALUES ($1, $2)",
            cid, owner_id,
        )
