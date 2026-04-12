"""Bridge connecting messenger gateways with streaming adapters."""
from __future__ import annotations

from typing import Callable

from breadmind.messenger.streaming import (
    get_stream_adapter,
    StreamChunk,
)


class StreamingBridge:
    """Wraps a messenger gateway's send method with streaming optimization."""

    def __init__(
        self,
        channel_type: str,
        send_fn: Callable,
        edit_fn: Callable | None = None,
    ) -> None:
        self._adapter = get_stream_adapter(channel_type)
        self._send_fn = send_fn
        self._edit_fn = edit_fn
        self._channel_ctx = self._build_ctx()

    def _build_ctx(self) -> dict:
        async def callback(
            action: str, text: str, msg_id: str | None = None,
        ):
            if action in ("send",):
                return await self._send_fn(text)
            elif action in ("edit", "update") and self._edit_fn:
                return await self._edit_fn(text, msg_id)
            elif action == "delta":
                return await self._send_fn(text)
            elif action == "done":
                return await self._send_fn(text)
            return ""

        return {"send_callback": callback}

    async def stream_text(self, text: str) -> None:
        """Stream a complete text through the adapter."""
        chunk_size = max(1, self._adapter._config.min_chars)
        for i in range(0, len(text), chunk_size):
            is_final = (i + chunk_size >= len(text))
            chunk = StreamChunk(text=text[i:i + chunk_size], is_final=is_final)
            await self._adapter.process_chunk(chunk, self._channel_ctx)

    async def stream_chunk(self, text: str, is_final: bool = False) -> None:
        """Stream a single chunk."""
        await self._adapter.process_chunk(
            StreamChunk(text=text, is_final=is_final),
            self._channel_ctx,
        )
