from uuid import uuid4


async def test_add_bookmark(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel, test_db, seed_workspace,
):
    _, owner_id = seed_workspace
    msg_id = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'hello')",
        msg_id, owner_workspace_id, owner_channel, owner_id,
    )
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/bookmarks",
        json={"message_id": str(msg_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text


async def test_list_bookmarks_returns_added(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel, test_db, seed_workspace,
):
    _, owner_id = seed_workspace
    msg_id = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 2, 'world')",
        msg_id, owner_workspace_id, owner_channel, owner_id,
    )
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/bookmarks",
        json={"message_id": str(msg_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    g = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/bookmarks",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert g.status_code == 200, g.text
    bms = g.json()["bookmarks"]
    assert any(b["message_id"] == str(msg_id) for b in bms)


async def test_remove_bookmark_empties_list(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel, test_db, seed_workspace,
):
    _, owner_id = seed_workspace
    msg_id = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 3, 'bye')",
        msg_id, owner_workspace_id, owner_channel, owner_id,
    )
    await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/bookmarks",
        json={"message_id": str(msg_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    d = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/bookmarks/{msg_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert d.status_code == 204, d.text
    g = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/bookmarks",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    bms = g.json()["bookmarks"]
    assert not any(b["message_id"] == str(msg_id) for b in bms)
