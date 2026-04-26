import pytest
from uuid import uuid4


async def test_oauth_app_round_trip(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    aid = uuid4()
    suffix = uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO oauth_apps "
        "(id, workspace_id, name, client_id, client_secret_hash, redirect_uris, scopes, created_by) "
        "VALUES ($1, $2, 'GitHubApp', $3, decode('aa','hex'), "
        "ARRAY['https://x.com/cb'], ARRAY['chat:write','channels:read'], $4)",
        aid, wid, f"cli-{suffix}", owner_id,
    )
    row = await test_db.fetchrow("SELECT name, scopes FROM oauth_apps WHERE id = $1", aid)
    assert row["name"] == "GitHubApp"
    assert "chat:write" in row["scopes"]


async def test_oauth_token_unique_hash(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    aid = uuid4()
    suffix = uuid4().hex[:8]
    token_hash = uuid4().bytes  # 16 bytes, unique per run
    await test_db.execute(
        "INSERT INTO oauth_apps "
        "(id, workspace_id, name, client_id, client_secret_hash, redirect_uris, scopes) "
        "VALUES ($1, $2, 'X', $3, decode('aa','hex'), ARRAY['/'], ARRAY['chat:write'])",
        aid, wid, f"cli-{suffix}",
    )
    await test_db.execute(
        "INSERT INTO oauth_tokens "
        "(id, app_id, workspace_id, token_kind, token_hash, scopes) "
        "VALUES (gen_random_uuid(), $1, $2, 'bot', $3, ARRAY['chat:write'])",
        aid, wid, token_hash,
    )
    with pytest.raises(Exception, match="duplicate key"):
        await test_db.execute(
            "INSERT INTO oauth_tokens "
            "(id, app_id, workspace_id, token_kind, token_hash, scopes) "
            "VALUES (gen_random_uuid(), $1, $2, 'bot', $3, ARRAY['chat:write'])",
            aid, wid, token_hash,
        )
