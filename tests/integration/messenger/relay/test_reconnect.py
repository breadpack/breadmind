# tests/integration/messenger/relay/test_reconnect.py
import json
import pytest
import websockets

pytestmark = pytest.mark.relay_integration


@pytest.mark.asyncio
@pytest.mark.skip(reason="M2b: pending relay last_ts_seq resume handler + api router mount + Redis bridge")
async def test_reconnect_backfill_missed_messages(compose_stack, two_users_one_channel):
    _, ws_base = compose_stack
    user_a, user_b, channel_id = two_users_one_channel

    # user A subscribes, captures last_ts_seq
    async with websockets.connect(f"{ws_base}/ws?token={user_a.token}") as ws:
        await ws.send(json.dumps({"type": "subscribe", "payload": {"channel_ids": [channel_id]}}))
        await ws.recv()  # subscribed ack

    # user B posts 5 messages while A disconnected
    import httpx
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {user_b.token}"}) as hc:
        for i in range(5):
            await hc.post(
                f"http://localhost:8080/api/v1/workspaces/{user_b.workspace_id}/channels/{channel_id}/messages",
                json={"body_md": f"msg-{i}"},
            )

    # A reconnects with last_ts_seq=0 → should get 5 messages
    async with websockets.connect(f"{ws_base}/ws?token={user_a.token}&last_ts_seq=0&channel_ids={channel_id}") as ws:
        received = []
        for _ in range(5):
            received.append(await ws.recv())
        bodies = [json.loads(m).get("payload", {}).get("body_md", "") for m in received]
        assert sorted(bodies) == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="M2b: pending body client_msg_id dedup + Redis bridge")
async def test_duplicate_client_msg_id_dedup(compose_stack, user_with_channel):
    _, ws_base = compose_stack
    user, channel_id = user_with_channel

    import httpx
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {user.token}"}) as hc:
        async with websockets.connect(f"{ws_base}/ws?token={user.token}") as ws:
            await ws.send(json.dumps({"type": "subscribe", "payload": {"channel_ids": [channel_id]}}))
            await ws.recv()

            for _ in range(2):
                await hc.post(
                    f"http://localhost:8080/api/v1/workspaces/{user.workspace_id}/channels/{channel_id}/messages",
                    json={"body_md": "once", "client_msg_id": "fixed-1"},
                )

            msg = await ws.recv()
            assert "once" in msg
            # second send should not result in another fanout
            import asyncio
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), 0.5)
