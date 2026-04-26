

async def test_pin_then_list(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": "pin me"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    rp = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
        headers=headers,
    )
    assert rp.status_code == 204, rp.text

    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/channels/{cid}/pins",
        headers=headers,
    )
    assert rl.status_code == 200, rl.text
    pins = rl.json()["pins"]
    assert len(pins) == 1
    assert pins[0]["id"] == mid


async def test_unpin_then_list_empty(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": "pin then unpin"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
        headers=headers,
    )
    ru = await messenger_app_client.delete(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
        headers=headers,
    )
    assert ru.status_code == 204, ru.text

    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/channels/{cid}/pins",
        headers=headers,
    )
    assert rl.status_code == 200, rl.text
    assert rl.json()["pins"] == []


async def test_pin_twice_idempotent(
    messenger_app_client, owner_token, owner_workspace_id, owner_channel,
):
    cid = owner_channel
    wid = owner_workspace_id
    headers = {"Authorization": f"Bearer {owner_token}"}

    r = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages",
        json={"text": "double pin"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]

    r1 = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
        headers=headers,
    )
    r2 = await messenger_app_client.post(
        f"/api/v1/workspaces/{wid}/channels/{cid}/messages/{mid}/pin",
        headers=headers,
    )
    assert r1.status_code == 204, r1.text
    assert r2.status_code == 204, r2.text

    rl = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/channels/{cid}/pins",
        headers=headers,
    )
    pins = rl.json()["pins"]
    assert len(pins) == 1
