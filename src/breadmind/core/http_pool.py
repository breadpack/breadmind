"""Global HTTP session pool manager for connection reuse.

Provides a singleton ``HTTPSessionManager`` that maintains named
``aiohttp.ClientSession`` instances backed by shared
``aiohttp.TCPConnector`` pools.  This avoids the cost of repeated
TCP + DNS + TLS handshakes that occur when sessions are created and
destroyed on every HTTP call.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)

__all__ = [
    "HTTPPoolConfig",
    "HTTPSessionManager",
    "get_session_manager",
]


@dataclass(frozen=True)
class HTTPPoolConfig:
    """Configuration for the HTTP connection pool."""

    total_limit: int = 100
    """Maximum number of simultaneous connections across all hosts."""

    per_host_limit: int = 30
    """Maximum number of simultaneous connections per host."""

    dns_cache_ttl: int = 300
    """DNS cache TTL in seconds."""

    keepalive_timeout: int = 30
    """Keep-alive timeout for idle connections in seconds."""

    connect_timeout: float = 10.0
    """Timeout for establishing a new connection in seconds."""


class HTTPSessionManager:
    """Manages named ``aiohttp.ClientSession`` instances with shared connectors.

    Sessions are created lazily on first access and can be closed
    individually or all at once (e.g. at application shutdown).
    """

    def __init__(self, config: HTTPPoolConfig | None = None) -> None:
        self._config = config or HTTPPoolConfig()
        self._sessions: dict[str, aiohttp.ClientSession] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, name: str = "default") -> aiohttp.ClientSession:
        """Return the session identified by *name*, creating it if needed."""
        session = self._sessions.get(name)
        if session is not None and not session.closed:
            return session

        async with self._lock:
            # Double-check after acquiring the lock.
            session = self._sessions.get(name)
            if session is not None and not session.closed:
                return session

            connector = aiohttp.TCPConnector(
                limit=self._config.total_limit,
                limit_per_host=self._config.per_host_limit,
                ttl_dns_cache=self._config.dns_cache_ttl,
                keepalive_timeout=self._config.keepalive_timeout,
            )
            timeout = aiohttp.ClientTimeout(
                connect=self._config.connect_timeout,
            )
            session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
            )
            self._sessions[name] = session
            logger.debug("Created HTTP session '%s'", name)
            return session

    async def close_session(self, name: str) -> None:
        """Close and remove a specific named session."""
        async with self._lock:
            session = self._sessions.pop(name, None)
        if session is not None and not session.closed:
            await session.close()
            logger.debug("Closed HTTP session '%s'", name)

    async def close_all(self) -> None:
        """Close every managed session.  Call this on app shutdown."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()

        for session in sessions:
            if not session.closed:
                await session.close()
        logger.debug("All HTTP sessions closed")

    def get_stats(self) -> dict:
        """Return basic statistics for each managed session."""
        stats: dict[str, dict] = {}
        for name, session in self._sessions.items():
            connector = session.connector
            info: dict = {"closed": session.closed}
            if isinstance(connector, aiohttp.TCPConnector):
                info["active_connections"] = len(connector._conns) if hasattr(connector, "_conns") else 0
                info["limit"] = connector.limit
                info["limit_per_host"] = connector.limit_per_host
            stats[name] = info
        return stats


# ── Singleton accessor ──────────────────────────────────────────────

_manager: HTTPSessionManager | None = None
_manager_lock = asyncio.Lock()


def get_session_manager(config: HTTPPoolConfig | None = None) -> HTTPSessionManager:
    """Return the process-wide ``HTTPSessionManager`` singleton.

    On first call the manager is created with the supplied *config*
    (or defaults).  Subsequent calls ignore *config* and return the
    existing instance.
    """
    global _manager  # noqa: PLW0603
    if _manager is None:
        _manager = HTTPSessionManager(config)
    return _manager


def _reset_session_manager() -> None:
    """Reset the singleton (for tests only)."""
    global _manager  # noqa: PLW0603
    _manager = None
