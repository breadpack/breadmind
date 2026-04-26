import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_add_reaction_201(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "react to me"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}/reactions",
        json={"emoji": ":+1:"},
        headers=headers,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_remove_reaction_204(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "react and remove"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}/reactions",
        json={"emoji": ":-1:"},
        headers=headers,
    )

    r = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}/reactions/:-1:",
        headers=headers,
    )
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_add_reaction_idempotent(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "double react"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    emoji = f":test-{uuid4().hex[:6]}:"
    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}/reactions",
        json={"emoji": emoji},
        headers=headers,
    )
    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}/reactions",
        json={"emoji": emoji},
        headers=headers,
    )
    # Neither should error
    assert r1.status_code in (200, 201), r1.text
    assert r2.status_code in (200, 201), r2.text

    # Should still count as 1
    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}/reactions",
        headers=headers,
    )
    reactions = rl.json()["reactions"]
    matching = [rx for rx in reactions if rx["emoji"] == emoji]
    assert len(matching) == 1
    assert matching[0]["count"] == 1


@pytest.mark.asyncio
async def test_list_reactions_count(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel, test_db, seed_workspace,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": "many reacts"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    # Add reaction from owner
    emoji = f":star-{uuid4().hex[:6]}:"
    await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/reactions",
        json={"emoji": emoji},
        headers=headers,
    )

    # Add reaction from a second user (insert directly to DB)
    from uuid import uuid4 as _uuid4
    uid2 = _uuid4()
    suffix = _uuid4().hex[:8]
    await test_db.execute(
        "INSERT INTO workspace_users (id, workspace_id, email, kind, display_name, role) "
        "VALUES ($1, $2, $3, 'human', 'U2', 'member')",
        uid2, wid, f"u2-{suffix}@test.com",
    )
    await test_db.execute(
        "INSERT INTO message_reactions (message_id, user_id, emoji) VALUES ($1, $2, $3)",
        mid, uid2, emoji,
    )

    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/reactions",
        headers=headers,
    )
    assert rl.status_code == 200, rl.text
    reactions = rl.json()["reactions"]
    matching = [rx for rx in reactions if rx["emoji"] == emoji]
    assert len(matching) == 1
    assert matching[0]["count"] == 2
