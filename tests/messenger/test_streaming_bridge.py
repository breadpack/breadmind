"""Tests for the streaming bridge."""
from __future__ import annotations

import pytest

from breadmind.messenger.streaming import (
    TelegramStreamAdapter,
    WebSocketStreamAdapter,
)
from breadmind.messenger.streaming_bridge import StreamingBridge


@pytest.fixture
def sent_messages() -> list[str]:
    return []


@pytest.fixture
def bridge(sent_messages: list[str]) -> StreamingBridge:
    async def send_fn(text: str) -> str:
        sent_messages.append(text)
        return f"msg_{len(sent_messages)}"

    return StreamingBridge("telegram", send_fn=send_fn)


async def test_bridge_streams_text(bridge: StreamingBridge, sent_messages: list[str]):
    await bridge.stream_text("Hello world, this is a test message.")
    assert len(sent_messages) > 0
    # All text should have been sent through the adapter
    combined = "".join(sent_messages)
    assert "Hello" in combined


async def test_bridge_stream_chunk(bridge: StreamingBridge, sent_messages: list[str]):
    await bridge.stream_chunk("First part ", is_final=False)
    await bridge.stream_chunk("second part", is_final=True)
    # At minimum the final chunk triggers a send
    assert len(sent_messages) >= 1


async def test_bridge_uses_correct_adapter():
    messages = []

    async def send_fn(text: str) -> str:
        messages.append(text)
        return "id"

    ws_bridge = StreamingBridge("websocket", send_fn=send_fn)
    assert isinstance(ws_bridge._adapter, WebSocketStreamAdapter)

    tg_bridge = StreamingBridge("telegram", send_fn=send_fn)
    assert isinstance(tg_bridge._adapter, TelegramStreamAdapter)
