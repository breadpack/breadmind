# tests/integration/messenger/relay/test_acl.py
import json
import pytest
import websockets

pytestmark = pytest.mark.relay_integration


@pytest.mark.asyncio
async def test_non_member_cannot_subscribe_to_private_channel(compose_stack, private_channel_setup):
    _, ws_base = compose_stack
    intruder, channel_id = private_channel_setup

    async with websockets.connect(f"{ws_base}/ws?token={intruder.token}") as ws:
        await ws.send(json.dumps({"type": "subscribe", "payload": {"channel_ids": [channel_id]}}))
        msg = await ws.recv()
        # subscribe should fail or subscribed list excludes channel
        payload = json.loads(msg)
        if payload["type"] == "subscribed":
            assert channel_id not in payload["payload"]["channel_ids"]
        else:
            assert payload["type"] == "error"
