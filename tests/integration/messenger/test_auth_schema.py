import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta

@pytest.mark.asyncio
async def test_session_round_trip(test_db, seed_workspace):
    wid, user_id = seed_workspace
    sid = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    # use uuid-derived bytes for refresh_token_hash to avoid UNIQUE collisions
    await test_db.execute(
        "INSERT INTO user_sessions (id, user_id, workspace_id, refresh_token_hash, expires_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        sid, user_id, wid, sid.bytes, expires,
    )
    row = await test_db.fetchrow("SELECT user_id FROM user_sessions WHERE id = $1", sid)
    assert row["user_id"] == user_id

@pytest.mark.asyncio
async def test_otp_pk_email_workspace(test_db):
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    suffix = uuid4().hex[:8]
    email = f"otp-{suffix}@x.com"
    slug = f"acme-{suffix}"
    await test_db.execute(
        "INSERT INTO email_otp (email, workspace_slug, code_hash, expires_at) "
        "VALUES ($1, $2, decode('aa','hex'), $3)", email, slug, expires,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO email_otp (email, workspace_slug, code_hash, expires_at) "
            "VALUES ($1, $2, decode('bb','hex'), $3)", email, slug, expires,
        )

@pytest.mark.asyncio
async def test_invite_token_unique(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    expires = datetime.now(timezone.utc) + timedelta(days=14)
    # generate a unique token_hash bytes from uuid to avoid UNIQUE collisions across runs
    token = uuid4().bytes  # 16 bytes
    await test_db.execute(
        "INSERT INTO workspace_invites "
        "(id, workspace_id, email, invited_by, token_hash, expires_at) "
        "VALUES (gen_random_uuid(), $1, 'a@x.com', $2, $3, $4)",
        wid, owner_id, token, expires,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO workspace_invites "
            "(id, workspace_id, email, invited_by, token_hash, expires_at) "
            "VALUES (gen_random_uuid(), $1, 'b@x.com', $2, $3, $4)",
            wid, owner_id, token, expires,
        )

@pytest.mark.asyncio
async def test_sso_config_one_per_workspace(test_db, seed_workspace):
    wid, _ = seed_workspace
    # First insert succeeds (workspace_id is PRIMARY KEY of sso_configs)
    await test_db.execute(
        "INSERT INTO sso_configs (workspace_id, provider, config) "
        "VALUES ($1, 'oidc', '{}'::jsonb)", wid,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO sso_configs (workspace_id, provider, config) "
            "VALUES ($1, 'saml', '{}'::jsonb)", wid,
        )
