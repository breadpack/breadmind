from httpx import AsyncClient


async def test_visible_channels_returns_owner_channels(
    messenger_app_client: AsyncClient,
    seed_workspace,
    owner_token,
    owner_channel,
):
    wid, owner_id = seed_workspace
    resp = await messenger_app_client.get(
        f"/api/v1/workspaces/{wid}/users/{owner_id}/visible-channels",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "channel_ids" in body
    assert str(owner_channel) in body["channel_ids"]
