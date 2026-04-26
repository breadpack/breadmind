import pytest


@pytest.mark.asyncio
async def test_thread_replies_returns_replies(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    # Post parent
    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "parent"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    parent_id = r.json()["id"]

    # Post 2 replies
    for i in range(2):
        rr = await messenger_app_client.post(
            f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
            json={"text": f"reply {i}", "parent_id": parent_id},
            headers=headers,
        )
        assert rr.status_code == 201, rr.text

    # GET replies
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{parent_id}/replies",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parent"]["id"] == parent_id
    assert len(body["replies"]) == 2
    # Replies should be ordered ASC by created_at
    assert body["replies"][0]["text"] == "reply 0"
    assert body["replies"][1]["text"] == "reply 1"


@pytest.mark.asyncio
async def test_empty_thread(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "lonely parent"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    parent_id = r.json()["id"]

    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{parent_id}/replies",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replies"] == []
    assert body["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_deleted_parent_404(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages",
        json={"text": "to be deleted"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    parent_id = r.json()["id"]

    # Soft-delete the parent
    rd = await messenger_app_client.delete(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{parent_id}",
        headers=headers,
    )
    assert rd.status_code == 204, rd.text

    # GET replies → 404
    r = await messenger_app_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/channels/{cid}/messages/{parent_id}/replies",
        headers=headers,
    )
    assert r.status_code == 404, r.text
