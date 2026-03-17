"""Tests for the Matrix protocol gateway."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.messenger.matrix_gw import MatrixGateway
from breadmind.messenger.router import IncomingMessage


@pytest.fixture
def gw():
    return MatrixGateway(
        homeserver="https://matrix.example.com",
        access_token="test-token",
        user_id="@bot:example.com",
    )


# ── 1. start / stop ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_and_stop(gw: MatrixGateway):
    """start() sets _connected and creates sync task; stop() cancels it."""
    with patch.object(gw, "_sync_loop", new_callable=AsyncMock) as mock_loop:
        # Make the mock coroutine block until cancelled
        mock_loop.side_effect = asyncio.CancelledError

        await gw.start()
        assert gw._connected is True
        assert gw._sync_task is not None

        await gw.stop()
        assert gw._connected is False


# ── 2. send ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_puts_message(gw: MatrixGateway):
    """send() issues a PUT to the Matrix send endpoint."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.put = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await gw.send("!room123:example.com", "hello")

    mock_session.put.assert_called_once()
    call_args = mock_session.put.call_args
    assert "/_matrix/client/v3/rooms/!room123:example.com/send/m.room.message/" in call_args[0][0]
    assert call_args[1]["json"] == {"msgtype": "m.text", "body": "hello"}
    assert "Bearer test-token" in call_args[1]["headers"]["Authorization"]


# ── 3. ask_approval ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_approval_sends_and_returns_id(gw: MatrixGateway):
    """ask_approval() sends an approval message and returns an action_id."""
    gw.send = AsyncMock()

    action_id = await gw.ask_approval(
        "!room:example.com", "deploy", {"env": "prod"}
    )

    assert isinstance(action_id, str)
    assert len(action_id) == 8
    gw.send.assert_awaited_once()
    sent_text = gw.send.call_args[0][1]
    assert "deploy" in sent_text
    assert action_id in sent_text


# ── 4. sync processes incoming message ──────────────────────────────

@pytest.mark.asyncio
async def test_sync_processes_incoming_message():
    """_sync_loop dispatches incoming messages to on_message callback."""
    received: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> str:
        received.append(msg)
        return "pong"

    gw = MatrixGateway(
        homeserver="https://matrix.example.com",
        access_token="tok",
        user_id="@bot:example.com",
        on_message=handler,
    )

    sync_response = {
        "next_batch": "s1",
        "rooms": {
            "join": {
                "!abc:example.com": {
                    "timeline": {
                        "events": [
                            {
                                "type": "m.room.message",
                                "sender": "@alice:example.com",
                                "content": {
                                    "msgtype": "m.text",
                                    "body": "ping",
                                },
                            }
                        ]
                    }
                }
            }
        },
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=sync_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    def session_factory(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            # After first sync, stop the gateway to exit the loop
            gw._connected = False
        return mock_session

    gw._connected = True
    gw.send = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=session_factory):
        await gw._sync_loop()

    assert len(received) == 1
    assert received[0].text == "ping"
    assert received[0].user_id == "@alice:example.com"
    assert received[0].channel_id == "!abc:example.com"
    assert received[0].platform == "matrix"
    gw.send.assert_awaited_once_with("!abc:example.com", "pong")


# ── 5. sync skips own messages ──────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_skips_own_messages():
    """_sync_loop ignores messages sent by the bot itself."""
    received: list[IncomingMessage] = []

    async def handler(msg: IncomingMessage) -> str:
        received.append(msg)
        return "reply"

    gw = MatrixGateway(
        homeserver="https://matrix.example.com",
        access_token="tok",
        user_id="@bot:example.com",
        on_message=handler,
    )

    sync_response = {
        "next_batch": "s2",
        "rooms": {
            "join": {
                "!room:example.com": {
                    "timeline": {
                        "events": [
                            {
                                "type": "m.room.message",
                                "sender": "@bot:example.com",  # own message
                                "content": {
                                    "msgtype": "m.text",
                                    "body": "echo",
                                },
                            }
                        ]
                    }
                }
            }
        },
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=sync_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    def session_factory(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            gw._connected = False
        return mock_session

    gw._connected = True
    gw.send = AsyncMock()

    with patch("aiohttp.ClientSession", side_effect=session_factory):
        await gw._sync_loop()

    assert len(received) == 0
    gw.send.assert_not_awaited()
