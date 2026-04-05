"""Channel-specific streaming optimization for messenger platforms."""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """A chunk of streamed content."""
    text: str
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamConfig:
    """Per-channel streaming configuration."""
    min_chars: int = 50         # minimum chars before sending an update
    max_chars: int = 4000       # maximum chars per message (platform limit)
    update_interval_ms: int = 1000  # minimum time between updates
    coalesce: bool = True       # merge consecutive small chunks
    code_fence_aware: bool = True  # don't split inside code fences


class BaseStreamAdapter(ABC):
    """Base class for channel-specific streaming adapters."""

    def __init__(self, config: StreamConfig | None = None) -> None:
        self._config = config or self.default_config()
        self._buffer = ""
        self._last_send_time: float = 0
        self._in_code_fence = False
        self._message_id: str | None = None  # for edit-based platforms

    @abstractmethod
    def default_config(self) -> StreamConfig:
        """Return platform-specific default config."""
        ...

    @abstractmethod
    async def send_initial(self, text: str, channel_ctx: dict) -> str:
        """Send initial message. Returns message ID for edit-based updates."""
        ...

    @abstractmethod
    async def send_update(self, text: str, message_id: str, channel_ctx: dict) -> None:
        """Update existing message (for edit-based platforms like Telegram/Slack)."""
        ...

    @abstractmethod
    async def send_final(self, text: str, message_id: str | None, channel_ctx: dict) -> None:
        """Send final complete message."""
        ...

    async def process_chunk(self, chunk: StreamChunk, channel_ctx: dict) -> None:
        """Process an incoming chunk with platform-optimized buffering."""
        self._buffer += chunk.text
        self._track_code_fence(chunk.text)

        now = time.monotonic() * 1000
        time_elapsed = now - self._last_send_time

        if chunk.is_final:
            await self._flush_final(channel_ctx)
            return

        # Don't send if inside a code fence (wait for it to close)
        if self._config.code_fence_aware and self._in_code_fence:
            return

        # Check if we should send an update
        should_send = (
            len(self._buffer) >= self._config.min_chars
            and time_elapsed >= self._config.update_interval_ms
        )

        if should_send:
            await self._flush_update(channel_ctx)

    async def _flush_update(self, channel_ctx: dict) -> None:
        """Send buffered content as an update."""
        if not self._buffer:
            return

        text = self._truncate(self._buffer)

        if self._message_id is None:
            self._message_id = await self.send_initial(text, channel_ctx)
        else:
            await self.send_update(text, self._message_id, channel_ctx)

        self._last_send_time = time.monotonic() * 1000

    async def _flush_final(self, channel_ctx: dict) -> None:
        """Send final complete message."""
        text = self._buffer
        await self.send_final(text, self._message_id, channel_ctx)
        self._buffer = ""
        self._message_id = None

    def _truncate(self, text: str) -> str:
        """Truncate to max_chars, trying to break at a natural boundary."""
        if len(text) <= self._config.max_chars:
            return text
        # Try to break at paragraph, then newline, then space
        for sep in ["\n\n", "\n", " "]:
            idx = text.rfind(sep, 0, self._config.max_chars)
            if idx > 0:
                return text[:idx]
        return text[:self._config.max_chars]

    def _track_code_fence(self, text: str) -> None:
        """Track whether we're inside a code fence."""
        count = text.count("```")
        if count % 2 == 1:
            self._in_code_fence = not self._in_code_fence


class TelegramStreamAdapter(BaseStreamAdapter):
    """Telegram: edit-based preview updates, then final message."""

    def default_config(self) -> StreamConfig:
        return StreamConfig(
            min_chars=100, max_chars=4096,
            update_interval_ms=1500,  # Telegram rate limit friendly
            coalesce=True, code_fence_aware=True,
        )

    async def send_initial(self, text: str, channel_ctx: dict) -> str:
        callback = channel_ctx.get("send_callback")
        if callback:
            return await callback("send", text)
        return ""

    async def send_update(self, text: str, message_id: str, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            await callback("edit", text, message_id)

    async def send_final(self, text: str, message_id: str | None, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            if message_id:
                await callback("edit", text, message_id)
            else:
                await callback("send", text)


class SlackStreamAdapter(BaseStreamAdapter):
    """Slack: block-based updates using chat.update API."""

    def default_config(self) -> StreamConfig:
        return StreamConfig(
            min_chars=80, max_chars=3000,
            update_interval_ms=2000,  # Slack API rate limit: ~1 req/sec
            coalesce=True, code_fence_aware=True,
        )

    async def send_initial(self, text: str, channel_ctx: dict) -> str:
        callback = channel_ctx.get("send_callback")
        if callback:
            return await callback("send", text)
        return ""

    async def send_update(self, text: str, message_id: str, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            await callback("update", text, message_id)

    async def send_final(self, text: str, message_id: str | None, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            if message_id:
                await callback("update", text, message_id)
            else:
                await callback("send", text)


class DiscordStreamAdapter(BaseStreamAdapter):
    """Discord: edit-based with 2000 char limit."""

    def default_config(self) -> StreamConfig:
        return StreamConfig(
            min_chars=80, max_chars=2000,
            update_interval_ms=1200,
            coalesce=True, code_fence_aware=True,
        )

    async def send_initial(self, text: str, channel_ctx: dict) -> str:
        callback = channel_ctx.get("send_callback")
        if callback:
            return await callback("send", text)
        return ""

    async def send_update(self, text: str, message_id: str, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            await callback("edit", text, message_id)

    async def send_final(self, text: str, message_id: str | None, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            if message_id:
                await callback("edit", text, message_id)
            else:
                await callback("send", text)


class WebSocketStreamAdapter(BaseStreamAdapter):
    """WebSocket: token-delta streaming (no editing needed)."""

    def default_config(self) -> StreamConfig:
        return StreamConfig(
            min_chars=1, max_chars=65536,
            update_interval_ms=50,  # near-realtime
            coalesce=False, code_fence_aware=False,
        )

    async def send_initial(self, text: str, channel_ctx: dict) -> str:
        callback = channel_ctx.get("send_callback")
        if callback:
            await callback("delta", text)
        return "ws"

    async def send_update(self, text: str, message_id: str, channel_ctx: dict) -> None:
        # For WebSocket, send only the new delta
        callback = channel_ctx.get("send_callback")
        if callback:
            await callback("delta", text)

    async def send_final(self, text: str, message_id: str | None, channel_ctx: dict) -> None:
        callback = channel_ctx.get("send_callback")
        if callback:
            await callback("done", text)


class CLIStreamAdapter(BaseStreamAdapter):
    """CLI: direct print, no buffering needed."""

    def default_config(self) -> StreamConfig:
        return StreamConfig(
            min_chars=1, max_chars=999999,
            update_interval_ms=0,
            coalesce=False, code_fence_aware=False,
        )

    async def send_initial(self, text: str, channel_ctx: dict) -> str:
        print(text, end="", flush=True)
        return "cli"

    async def send_update(self, text: str, message_id: str, channel_ctx: dict) -> None:
        print(text, end="", flush=True)

    async def send_final(self, text: str, message_id: str | None, channel_ctx: dict) -> None:
        print(text, flush=True)


# Factory
_ADAPTERS: dict[str, type[BaseStreamAdapter]] = {
    "telegram": TelegramStreamAdapter,
    "slack": SlackStreamAdapter,
    "discord": DiscordStreamAdapter,
    "websocket": WebSocketStreamAdapter,
    "cli": CLIStreamAdapter,
}


def get_stream_adapter(channel: str, config: StreamConfig | None = None) -> BaseStreamAdapter:
    """Get the appropriate streaming adapter for a channel."""
    adapter_cls = _ADAPTERS.get(channel, WebSocketStreamAdapter)
    return adapter_cls(config)


def register_stream_adapter(channel: str, adapter_cls: type[BaseStreamAdapter]) -> None:
    """Register a custom streaming adapter for a channel."""
    _ADAPTERS[channel] = adapter_cls
