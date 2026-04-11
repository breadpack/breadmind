"""Simple sliding-window rate limiter scoped by actor id."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, *, window_seconds: float = 60.0, max_events: int = 20) -> None:
        self._window = float(window_seconds)
        self._max = int(max_events)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, actor: str, *, now: float | None = None) -> bool:
        """Return True if this event is allowed; False if the actor is over cap."""
        ts = time.monotonic() if now is None else float(now)
        q = self._events[actor]
        cutoff = ts - self._window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= self._max:
            return False
        q.append(ts)
        return True
