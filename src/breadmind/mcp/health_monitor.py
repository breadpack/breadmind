"""MCP server health monitoring with auto-restart support."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ServerHealth:
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: float = 0
    last_healthy: float = 0
    consecutive_failures: int = 0
    total_checks: int = 0
    total_failures: int = 0
    uptime_seconds: float = 0
    started_at: float = 0
    restart_count: int = 0
    last_error: str = ""
    response_time_ms: float = 0


class MCPHealthMonitor:
    """Monitors MCP server health with periodic checks and auto-restart.

    Features:
    - Periodic health checks (ping via JSON-RPC)
    - Auto-restart on consecutive failures
    - Uptime tracking
    - Response time monitoring
    - Degraded state detection (slow but responsive)
    """

    def __init__(
        self,
        check_interval_seconds: int = 60,
        max_consecutive_failures: int = 3,
        auto_restart: bool = True,
        response_time_threshold_ms: float = 5000,
    ) -> None:
        self._interval = check_interval_seconds
        self._max_failures = max_consecutive_failures
        self._auto_restart = auto_restart
        self._threshold_ms = response_time_threshold_ms
        self._servers: dict[str, ServerHealth] = {}
        self._running = False

    def register_server(self, name: str) -> None:
        """Register a server for health monitoring."""
        if name in self._servers:
            logger.warning("Server %s already registered, resetting health", name)
        self._servers[name] = ServerHealth(
            name=name,
            started_at=time.time(),
        )

    def unregister_server(self, name: str) -> None:
        """Remove a server from health monitoring."""
        self._servers.pop(name, None)

    def record_check(
        self,
        name: str,
        healthy: bool,
        response_time_ms: float = 0,
        error: str = "",
    ) -> ServerHealth:
        """Record a health check result and update server status."""
        if name not in self._servers:
            raise KeyError(f"Server '{name}' is not registered")

        health = self._servers[name]
        now = time.time()
        health.last_check = now
        health.total_checks += 1
        health.response_time_ms = response_time_ms

        if healthy:
            health.consecutive_failures = 0
            health.last_healthy = now
            health.last_error = ""
            if health.started_at > 0:
                health.uptime_seconds = now - health.started_at

            if response_time_ms > self._threshold_ms:
                health.status = HealthStatus.DEGRADED
            else:
                health.status = HealthStatus.HEALTHY
        else:
            health.consecutive_failures += 1
            health.total_failures += 1
            health.last_error = error

            if health.consecutive_failures >= self._max_failures:
                health.status = HealthStatus.UNHEALTHY
            else:
                health.status = HealthStatus.DEGRADED

        return health

    def get_health(self, name: str) -> ServerHealth | None:
        """Get health info for a specific server."""
        return self._servers.get(name)

    def get_all_health(self) -> list[ServerHealth]:
        """Get health info for all registered servers."""
        return list(self._servers.values())

    def get_summary(self) -> dict:
        """Get summary: total, healthy, degraded, unhealthy counts."""
        all_health = self.get_all_health()
        return {
            "total": len(all_health),
            "healthy": sum(
                1 for h in all_health if h.status == HealthStatus.HEALTHY
            ),
            "degraded": sum(
                1 for h in all_health if h.status == HealthStatus.DEGRADED
            ),
            "unhealthy": sum(
                1 for h in all_health if h.status == HealthStatus.UNHEALTHY
            ),
            "unknown": sum(
                1 for h in all_health if h.status == HealthStatus.UNKNOWN
            ),
        }

    def needs_restart(self, name: str) -> bool:
        """Check if server needs auto-restart based on consecutive failures."""
        if not self._auto_restart:
            return False
        health = self._servers.get(name)
        if health is None:
            return False
        return health.consecutive_failures >= self._max_failures

    def record_restart(self, name: str) -> None:
        """Record that a server was restarted."""
        health = self._servers.get(name)
        if health is None:
            raise KeyError(f"Server '{name}' is not registered")
        health.restart_count += 1
        health.consecutive_failures = 0
        health.status = HealthStatus.UNKNOWN
        health.started_at = time.time()
        health.last_error = ""

    def get_uptime(self, name: str) -> float:
        """Get current uptime in seconds for a server."""
        health = self._servers.get(name)
        if health is None:
            return 0
        if health.started_at <= 0:
            return 0
        return time.time() - health.started_at

    @property
    def running(self) -> bool:
        return self._running

    @property
    def check_interval(self) -> int:
        return self._interval

    @property
    def auto_restart_enabled(self) -> bool:
        return self._auto_restart
