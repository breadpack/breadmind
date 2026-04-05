"""Tests for channel-specific streaming adapters."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from breadmind.messenger.streaming import (
    BaseStreamAdapter,
    CLIStreamAdapter,
    DiscordStreamAdapter,
    SlackStreamAdapter,
    StreamChunk,
    StreamConfig,
    TelegramStreamAdapter,
    WebSocketStreamAdapter,
    get_stream_adapter,
    register_stream_adapter,
)


# ── Helpers ──


def _make_recording_ctx() -> tuple[dict, list]:
    """Create a channel_ctx with a recording callback."""
    calls: list[tuple] = []

    async def callback(*args):
        calls.append(args)
        # Return a fake message ID for send actions
        if args[0] in ("send",):
            return "msg-123"
        return None

    return {"send_callback": callback}, calls


# ── Config tests ──


async def test_telegram_adapter_default_config():
    adapter = TelegramStreamAdapter()
    cfg = adapter._config
    assert cfg.min_chars == 100
    assert cfg.max_chars == 4096
    assert cfg.update_interval_ms == 1500
    assert cfg.coalesce is True
    assert cfg.code_fence_aware is True


async def test_slack_adapter_default_config():
    adapter = SlackStreamAdapter()
    cfg = adapter._config
    assert cfg.min_chars == 80
    assert cfg.max_chars == 3000
    assert cfg.update_interval_ms == 2000
    assert cfg.coalesce is True


async def test_discord_adapter_max_chars():
    adapter = DiscordStreamAdapter()
    assert adapter._config.max_chars == 2000


async def test_websocket_adapter_near_realtime():
    adapter = WebSocketStreamAdapter()
    cfg = adapter._config
    assert cfg.min_chars == 1
    assert cfg.update_interval_ms == 50
    assert cfg.coalesce is False
    assert cfg.code_fence_aware is False


async def test_cli_adapter_direct_print(capsys):
    adapter = CLIStreamAdapter()
    ctx: dict = {}

    msg_id = await adapter.send_initial("Hello", ctx)
    assert msg_id == "cli"
    captured = capsys.readouterr()
    assert captured.out == "Hello"

    await adapter.send_update(" world", "cli", ctx)
    captured = capsys.readouterr()
    assert captured.out == " world"

    await adapter.send_final("Done!", None, ctx)
    captured = capsys.readouterr()
    assert captured.out == "Done!\n"


# ── Chunk processing tests ──


async def test_process_chunk_buffers_small_chunks():
    """Small chunks below min_chars should be buffered, not sent."""
    adapter = TelegramStreamAdapter()
    ctx, calls = _make_recording_ctx()

    # Send a tiny chunk (below min_chars=100)
    await adapter.process_chunk(StreamChunk(text="Hi"), ctx)
    assert len(calls) == 0
    assert adapter._buffer == "Hi"


async def test_process_chunk_flushes_on_threshold():
    """Buffer should flush when min_chars is reached and enough time has passed."""
    adapter = WebSocketStreamAdapter()  # min_chars=1, interval=50ms
    ctx, calls = _make_recording_ctx()

    # WebSocket has very low thresholds - first chunk should trigger send
    # Set last_send_time to 0 so time_elapsed is large
    adapter._last_send_time = 0

    await adapter.process_chunk(StreamChunk(text="Hello world"), ctx)

    # Should have sent initial message
    assert len(calls) == 1
    assert calls[0][0] == "delta"
    assert calls[0][1] == "Hello world"


async def test_process_chunk_final_flushes_all():
    """A final chunk should flush everything regardless of thresholds."""
    adapter = TelegramStreamAdapter()
    ctx, calls = _make_recording_ctx()

    # Buffer some text
    await adapter.process_chunk(StreamChunk(text="Partial "), ctx)
    assert len(calls) == 0

    # Send final chunk
    await adapter.process_chunk(StreamChunk(text="response.", is_final=True), ctx)

    # Should have called send_final
    assert len(calls) == 1
    assert calls[0][0] == "send"
    assert "Partial response." in calls[0][1]


async def test_code_fence_aware_buffering():
    """Should not send updates while inside a code fence."""
    config = StreamConfig(
        min_chars=1, max_chars=4000,
        update_interval_ms=0,
        coalesce=True, code_fence_aware=True,
    )
    adapter = TelegramStreamAdapter(config)
    ctx, calls = _make_recording_ctx()
    adapter._last_send_time = 0

    # Open a code fence
    await adapter.process_chunk(StreamChunk(text="```python\n"), ctx)
    # Should NOT send because we're inside a code fence
    assert len(calls) == 0

    # Still inside the fence
    await adapter.process_chunk(StreamChunk(text="x = 1\n"), ctx)
    assert len(calls) == 0

    # Close the code fence
    await adapter.process_chunk(StreamChunk(text="```\n"), ctx)
    # Now it should send (fence closed, thresholds met)
    assert len(calls) == 1


async def test_truncate_at_natural_boundary():
    """Truncation should prefer natural boundaries like newlines."""
    adapter = DiscordStreamAdapter()

    # Text longer than max_chars (2000) with newline inside the limit
    text = "A" * 1900 + "\n" + "B" * 200
    result = adapter._truncate(text)
    assert len(result) <= 2000
    # Should break at the newline (rfind returns index of \n, so result is up to that point)
    assert len(result) == 1901  # includes the newline character

    # Text with space boundary
    text2 = "word " * 500  # 2500 chars
    result2 = adapter._truncate(text2)
    assert len(result2) <= 2000
    # Should break at a space boundary
    assert not result2.endswith("wor")  # didn't break mid-word


# ── Factory tests ──


async def test_get_stream_adapter_factory():
    adapter = get_stream_adapter("telegram")
    assert isinstance(adapter, TelegramStreamAdapter)

    adapter = get_stream_adapter("slack")
    assert isinstance(adapter, SlackStreamAdapter)

    adapter = get_stream_adapter("discord")
    assert isinstance(adapter, DiscordStreamAdapter)

    adapter = get_stream_adapter("websocket")
    assert isinstance(adapter, WebSocketStreamAdapter)

    adapter = get_stream_adapter("cli")
    assert isinstance(adapter, CLIStreamAdapter)

    # Unknown channel falls back to WebSocket
    adapter = get_stream_adapter("unknown_channel")
    assert isinstance(adapter, WebSocketStreamAdapter)


async def test_register_custom_adapter():
    class CustomAdapter(BaseStreamAdapter):
        def default_config(self) -> StreamConfig:
            return StreamConfig(min_chars=10, max_chars=500)

        async def send_initial(self, text, channel_ctx):
            return "custom"

        async def send_update(self, text, message_id, channel_ctx):
            pass

        async def send_final(self, text, message_id, channel_ctx):
            pass

    register_stream_adapter("custom_platform", CustomAdapter)
    adapter = get_stream_adapter("custom_platform")
    assert isinstance(adapter, CustomAdapter)
    assert adapter._config.max_chars == 500
