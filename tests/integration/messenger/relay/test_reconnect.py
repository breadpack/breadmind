# tests/integration/messenger/relay/test_reconnect.py
import asyncio
import json

import httpx
import pytest
import websockets

pytestmark = pytest.mark.relay_integration


@pytest.mark.asyncio
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
                json={"text": f"msg-{i}"},
            )

    # A reconnects with last_ts_seq=0 → should get 5 messages
    async with websockets.connect(f"{ws_base}/ws?token={user_a.token}&last_ts_seq=0&channel_ids={channel_id}") as ws:
        received = []
        for _ in range(5):
            received.append(await ws.recv())
        bodies = [json.loads(m).get("payload", {}).get("text", "") for m in received]
        assert sorted(bodies) == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]


@pytest.mark.asyncio
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
                    json={"text": "once", "client_msg_id": "fixed-1"},
                )

            msg = await ws.recv()
            assert "once" in msg
            # second send should not result in another fanout
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), 0.5)


@pytest.mark.asyncio
async def test_resume_replays_via_backfill(compose_stack, two_users_one_channel):
    """Disconnect after a baseline message, post more while offline, then
    reconnect with a per-channel resume cursor — relay must replay missed
    events as `backfill` envelopes BEFORE the `subscribed` ack.

    Wire ordering (Task 4): for each ChannelResume[i] > 0, the relay calls
    coreClient.BackfillSince and emits one TypeBackfill envelope per
    replayed event, THEN registers the live subscription, THEN sends the
    single TypeSubscribed ack. Live fan-out only targets registered conns,
    so the client sees "history -> ack -> live" deterministically.
    """
    api, ws_base = compose_stack
    admin, member, channel_id = two_users_one_channel

    # Member connects, subscribes, captures ts_seq of the baseline message.
    async with websockets.connect(f"{ws_base}/ws?token={member.token}") as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "payload": {"channel_ids": [channel_id]},
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        assert ack["type"] == "subscribed"

        async with httpx.AsyncClient(
            base_url=api,
            headers={"Authorization": f"Bearer {admin.token}"},
        ) as hc:
            r0 = await hc.post(
                f"/api/v1/workspaces/{admin.workspace_id}"
                f"/channels/{channel_id}/messages",
                json={"text": "m0"},
            )
            assert r0.status_code == 201

        m0 = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
        # Live envelope ts is Slack-format: "<epoch>.<6-digit-ts_seq>". Parse
        # the seq portion to use as the resume cursor; ts_seq itself is not
        # carried as a numeric field in the live fan-out payload.
        ts_str = m0["payload"]["ts"]
        last_ts = int(ts_str.split(".")[1])
        # ws context exits here -> connection closed.

    # Admin posts m1, m2 while the member is disconnected.
    async with httpx.AsyncClient(
        base_url=api,
        headers={"Authorization": f"Bearer {admin.token}"},
    ) as hc:
        await hc.post(
            f"/api/v1/workspaces/{admin.workspace_id}"
            f"/channels/{channel_id}/messages",
            json={"text": "m1"},
        )
        await hc.post(
            f"/api/v1/workspaces/{admin.workspace_id}"
            f"/channels/{channel_id}/messages",
            json={"text": "m2"},
        )

    # Member reconnects with per-channel resume cursor.
    async with websockets.connect(f"{ws_base}/ws?token={member.token}") as ws2:
        await ws2.send(json.dumps({
            "type": "subscribe",
            "payload": {
                "channel_ids": [channel_id],
                "channel_resume": [last_ts],
            },
        }))
        # Drain frames until the Subscribed ack arrives. Backfill envelopes
        # are emitted before the ack (Task 4 ordering guarantee). Cap the
        # loop at a generous bound to avoid hanging on an unexpected stream.
        backfilled: list = []
        for _ in range(10):
            ev = json.loads(await asyncio.wait_for(ws2.recv(), 2.0))
            if ev["type"] == "backfill":
                backfilled.append(ev["payload"])
            elif ev["type"] == "subscribed":
                break

        # At minimum the missed events m1 + m2 must be replayed. The exact
        # count depends on the Python `since_ts_seq` filter behaviour; the
        # client-side guarantee we assert is "missed messages are present".
        assert len(backfilled) >= 2

        texts: list[str] = []
        for bp in backfilled:
            ev_raw = bp["event"]
            inner = json.loads(ev_raw) if isinstance(ev_raw, (str, bytes)) else ev_raw
            # Backfill events come from GET .../messages which serializes the
            # full MessageResp (text included).
            text = inner.get("text") or inner.get("payload", {}).get("text", "")
            texts.append(text)
        assert "m1" in texts and "m2" in texts
