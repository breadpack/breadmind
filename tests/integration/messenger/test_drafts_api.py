from uuid import uuid4


async def test_upsert_then_get_draft(messenger_app_client, owner_token, owner_workspace_id, owner_channel):
    cid = owner_channel
    r = await messenger_app_client.put(
        f"/api/v1/workspaces/{owner_workspace_id}/drafts",
        json={"channel_id": str(cid), "text": "draft text"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204, r.text
    g = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/drafts",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    drafts = g.json()["drafts"]
    assert any(d["text"] == "draft text" for d in drafts)


async def test_draft_per_thread_independent(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel, test_db, seed_workspace,
):
    _, owner_id = seed_workspace
    parent_id = uuid4()
    await test_db.execute(
        "INSERT INTO messages (id, workspace_id, channel_id, author_id, ts_seq, text) "
        "VALUES ($1, $2, $3, $4, 1, 'parent')",
        parent_id, owner_workspace_id, owner_channel, owner_id,
    )
    await messenger_app_client.put(
        f"/api/v1/workspaces/{owner_workspace_id}/drafts",
        json={"channel_id": str(owner_channel), "text": "channel draft"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await messenger_app_client.put(
        f"/api/v1/workspaces/{owner_workspace_id}/drafts",
        json={"channel_id": str(owner_channel),
              "thread_parent_id": str(parent_id),
              "text": "thread draft"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    g = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/drafts",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    drafts = g.json()["drafts"]
    texts = [d["text"] for d in drafts]
    assert "channel draft" in texts
    assert "thread draft" in texts
