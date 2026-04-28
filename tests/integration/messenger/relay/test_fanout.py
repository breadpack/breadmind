# tests/integration/messenger/relay/test_fanout.py
import json
import asyncio

import pytest
import websockets

pytestmark = pytest.mark.relay_integration


@pytest.mark.asyncio
@pytest.mark.skip(reason="M2b: pending api router mount + Redis bridge + body_md/text field unification")
async def test_message_fanout_to_two_clients(compose_stack, two_users_one_channel):
    _, ws_base = compose_stack
    user_a, user_b, channel_id = two_users_one_channel

    async with websockets.connect(f"{ws_base}/ws?token={user_a.token}") as ws_a, \
               websockets.connect(f"{ws_base}/ws?token={user_b.token}") as ws_b:
        await ws_a.send(json.dumps({"type": "subscribe", "payload": {"channel_ids": [channel_id]}}))
        await ws_b.send(json.dumps({"type": "subscribe", "payload": {"channel_ids": [channel_id]}}))
        # drain subscribed acks
        await ws_a.recv()
        await ws_b.recv()

        # user A posts
        import httpx
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {user_a.token}"}) as hc:
            resp = await hc.post(
                f"http://localhost:8080/api/v1/workspaces/{user_a.workspace_id}/channels/{channel_id}/messages",
                json={"body_md": "hello"},
            )
            assert resp.status_code == 201

        # both clients receive
        msg_a = await asyncio.wait_for(ws_a.recv(), 3)
        msg_b = await asyncio.wait_for(ws_b.recv(), 3)
        assert "hello" in msg_a
        assert "hello" in msg_b


@pytest.mark.asyncio
@pytest.mark.skip(reason="M2b: pending client-side TypeTyping command branch in relay WS handler")
async def test_typing_broadcast(compose_stack, two_users_one_channel):
    _, ws_base = compose_stack
    user_a, user_b, channel_id = two_users_one_channel

    async with websockets.connect(f"{ws_base}/ws?token={user_a.token}") as ws_a, \
               websockets.connect(f"{ws_base}/ws?token={user_b.token}") as ws_b:
        for ws in (ws_a, ws_b):
            await ws.send(json.dumps({"type": "subscribe", "payload": {"channel_ids": [channel_id]}}))
            await ws.recv()

        await ws_a.send(json.dumps({"type": "typing", "payload": {"channel_id": channel_id}}))
        msg = await asyncio.wait_for(ws_b.recv(), 3)
        assert '"typing"' in msg
        assert user_a.id in msg
