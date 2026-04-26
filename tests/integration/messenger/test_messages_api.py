from uuid import uuid4


async def test_post_message(messenger_app_client, owner_token, owner_workspace_id, owner_channel):
    cid = owner_channel
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "hello", "blocks": []},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    msg = r.json()
    assert msg["text"] == "hello"
    assert msg["kind"] == "text"


async def test_idempotency_key_dedupes(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    key = f"idem-{uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {owner_token}", "Idempotency-Key": key}
    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "hi"}, headers=headers,
    )
    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "hi"}, headers=headers,
    )
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert r1.json()["id"] == r2.json()["id"]


async def test_edit_message(messenger_app_client, owner_token, owner_workspace_id, owner_channel):
    cid = owner_channel
    create = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "original"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    mid = create.json()["id"]
    r = await messenger_app_client.patch(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}",
        json={"text": "edited"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "edited"
    assert body["edited_at"] is not None


async def test_soft_delete_message(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    create = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "to delete"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    mid = create.json()["id"]
    r = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{mid}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204, r.text


async def test_history_pagination(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    for i in range(5):
        await messenger_app_client.post(
            f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
            json={"text": f"msg {i}"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        params={"limit": 3},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    body = r.json()
    assert len(body["messages"]) == 3
    assert body["pagination"]["has_more"] is True
