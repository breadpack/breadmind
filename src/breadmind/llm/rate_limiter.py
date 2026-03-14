"""Token and request rate limiting with exponential backoff."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone


class RateLimiter:
    """Token and request rate limiting with exponential backoff."""

    def __init__(
        self,
        max_requests_per_minute: int = 60,
        max_tokens_per_minute: int = 100_000,
    ):
        self._max_rpm = max_requests_per_minute
        self._max_tpm = max_tokens_per_minute
        self._request_times: deque[datetime] = deque()
        self._token_usage: deque[tuple[datetime, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int = 0) -> None:
        """Wait if rate limit would be exceeded. Implements exponential backoff."""
        backoff = 1.0
        max_backoff = 60.0

        while True:
            async with self._lock:
                self._cleanup_old_entries()

                current_rpm = len(self._request_times)
                current_tpm = sum(tokens for _, tokens in self._token_usage)

                rpm_ok = current_rpm < self._max_rpm
                tpm_ok = current_tpm + estimated_tokens <= self._max_tpm

                if rpm_ok and tpm_ok:
                    now = datetime.now(timezone.utc)
                    self._request_times.append(now)
                    if estimated_tokens > 0:
                        self._token_usage.append((now, estimated_tokens))
                    return

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    async def record_usage(self, tokens_used: int) -> None:
        """Record actual token usage after a successful call."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            self._token_usage.append((now, tokens_used))

    def get_usage_stats(self) -> dict:
        """Return current usage stats: rpm, tpm, remaining capacity."""
        self._cleanup_old_entries()

        current_rpm = len(self._request_times)
        current_tpm = sum(tokens for _, tokens in self._token_usage)

        return {
            "requests_per_minute": current_rpm,
            "tokens_per_minute": current_tpm,
            "remaining_rpm": max(0, self._max_rpm - current_rpm),
            "remaining_tpm": max(0, self._max_tpm - current_tpm),
            "max_rpm": self._max_rpm,
            "max_tpm": self._max_tpm,
        }

    def _cleanup_old_entries(self) -> None:
        """Remove entries older than 1 minute."""
        now = datetime.now(timezone.utc)
        one_minute_ago = now.timestamp() - 60.0

        while self._request_times and self._request_times[0].timestamp() < one_minute_ago:
            self._request_times.popleft()

        while self._token_usage and self._token_usage[0][0].timestamp() < one_minute_ago:
            self._token_usage.popleft()
