"""Simple in-memory IP-based rate limiter."""

import time
from collections import defaultdict


class RateLimiter:
    """Simple in-memory IP-based rate limiter.

    Tracks per-IP request counts (sliding window) and auth failure counts
    to protect against brute-force attacks.
    """

    def __init__(self, requests_per_minute: int = 60, auth_fail_limit: int = 5):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._auth_fails: dict[str, list[float]] = defaultdict(list)
        self._rpm = requests_per_minute
        self._auth_fail_limit = auth_fail_limit

    def is_allowed(self, ip: str) -> bool:
        """Check if the IP is within the general rate limit (requests per minute)."""
        now = time.time()
        # Clean old entries
        self._requests[ip] = [t for t in self._requests[ip] if now - t < 60]
        self._requests[ip].append(now)
        return len(self._requests[ip]) <= self._rpm

    def record_auth_fail(self, ip: str) -> None:
        """Record an authentication failure for the given IP."""
        now = time.time()
        self._auth_fails[ip] = [t for t in self._auth_fails[ip] if now - t < 300]
        self._auth_fails[ip].append(now)

    def is_auth_blocked(self, ip: str) -> bool:
        """Check if the IP is blocked due to too many auth failures (5-minute window)."""
        now = time.time()
        self._auth_fails[ip] = [t for t in self._auth_fails[ip] if now - t < 300]
        return len(self._auth_fails[ip]) >= self._auth_fail_limit
