"""Deep health check system for BreadMind components."""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 3.0


class HealthStatus(str, Enum):
    """Component health status."""
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"


@dataclass
class ComponentHealth:
    """Result of a single component health check."""
    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    detail: str | None = None


class HealthChecker:
    """Runs health checks against all BreadMind subsystems.

    Each check is independent -- a failure in one does not affect
    the others.  All checks are subject to a configurable timeout
    (default 3 s).
    """

    def __init__(
        self,
        db=None,
        providers: list | None = None,
        mcp_manager=None,
        timeout: float = CHECK_TIMEOUT_SECONDS,
    ) -> None:
        self._db = db
        self._providers: list = providers or []
        self._mcp_manager = mcp_manager
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    async def check_database(self) -> ComponentHealth:
        """Test database connectivity with ``SELECT 1``."""
        if self._db is None:
            return ComponentHealth(
                name="database",
                status=HealthStatus.healthy,
                detail="no database configured (file-based storage)",
            )
        try:
            start = time.monotonic()
            healthy = await asyncio.wait_for(
                self._db.health_check(), timeout=self._timeout,
            )
            latency = (time.monotonic() - start) * 1000
            if healthy:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.healthy,
                    latency_ms=round(latency, 2),
                    detail="connected",
                )
            return ComponentHealth(
                name="database",
                status=HealthStatus.unhealthy,
                latency_ms=round(latency, 2),
                detail="health check returned false",
            )
        except asyncio.TimeoutError:
            return ComponentHealth(
                name="database",
                status=HealthStatus.unhealthy,
                detail="timeout",
            )
        except Exception as exc:
            return ComponentHealth(
                name="database",
                status=HealthStatus.unhealthy,
                detail=str(exc)[:120],
            )

    async def check_llm_provider(self, provider) -> ComponentHealth:
        """Check a single LLM provider.

        If the provider exposes ``health_check()``, call it; otherwise
        report the provider as *healthy* (we cannot verify without a
        concrete call).
        """
        name = getattr(provider, "name", None) or type(provider).__name__
        health_fn = getattr(provider, "health_check", None)
        if health_fn is None or not callable(health_fn):
            return ComponentHealth(
                name=f"llm:{name}",
                status=HealthStatus.healthy,
                detail="skipped (no health_check method)",
            )
        try:
            start = time.monotonic()
            ok = await asyncio.wait_for(health_fn(), timeout=self._timeout)
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name=f"llm:{name}",
                status=HealthStatus.healthy if ok else HealthStatus.unhealthy,
                latency_ms=round(latency, 2),
                detail="ok" if ok else "provider health check failed",
            )
        except asyncio.TimeoutError:
            return ComponentHealth(
                name=f"llm:{name}",
                status=HealthStatus.unhealthy,
                detail="timeout",
            )
        except Exception as exc:
            return ComponentHealth(
                name=f"llm:{name}",
                status=HealthStatus.unhealthy,
                detail=str(exc)[:120],
            )

    async def check_mcp_servers(self) -> ComponentHealth:
        """Check MCP server availability."""
        if self._mcp_manager is None:
            return ComponentHealth(
                name="mcp",
                status=HealthStatus.healthy,
                detail="no MCP manager configured",
            )
        try:
            start = time.monotonic()
            servers = await asyncio.wait_for(
                self._mcp_manager.list_servers(), timeout=self._timeout,
            )
            latency = (time.monotonic() - start) * 1000

            if not servers:
                return ComponentHealth(
                    name="mcp",
                    status=HealthStatus.healthy,
                    latency_ms=round(latency, 2),
                    detail="no servers configured",
                )

            total = len(servers)
            # Try individual health checks if the manager supports it
            healthy_count = 0
            health_fn = getattr(self._mcp_manager, "health_check", None)
            if health_fn and callable(health_fn):
                for srv in servers:
                    srv_name = getattr(srv, "name", None) or str(srv)
                    try:
                        ok = await asyncio.wait_for(
                            health_fn(srv_name), timeout=self._timeout,
                        )
                        if ok:
                            healthy_count += 1
                    except Exception:
                        pass
            else:
                # Cannot check individual servers; assume all healthy
                healthy_count = total

            if healthy_count == total:
                status = HealthStatus.healthy
            elif healthy_count > 0:
                status = HealthStatus.degraded
            else:
                status = HealthStatus.unhealthy

            return ComponentHealth(
                name="mcp",
                status=status,
                latency_ms=round(latency, 2),
                detail=f"{healthy_count}/{total} servers healthy",
            )
        except asyncio.TimeoutError:
            return ComponentHealth(
                name="mcp",
                status=HealthStatus.unhealthy,
                detail="timeout",
            )
        except Exception as exc:
            return ComponentHealth(
                name="mcp",
                status=HealthStatus.unhealthy,
                detail=str(exc)[:120],
            )

    async def check_memory(self) -> ComponentHealth:
        """Check system memory usage using platform-native methods.

        Does **not** depend on ``psutil``.
        """
        try:
            start = time.monotonic()
            system = platform.system()

            if system == "Linux":
                info = await self._read_linux_memory()
            elif system == "Darwin":
                info = await self._read_macos_memory()
            elif system == "Windows":
                info = await self._read_windows_memory()
            else:
                return ComponentHealth(
                    name="memory",
                    status=HealthStatus.healthy,
                    detail=f"unsupported platform: {system}",
                )

            latency = (time.monotonic() - start) * 1000
            used_pct = info.get("used_percent", 0.0)

            if used_pct < 85:
                status = HealthStatus.healthy
            elif used_pct < 95:
                status = HealthStatus.degraded
            else:
                status = HealthStatus.unhealthy

            return ComponentHealth(
                name="memory",
                status=status,
                latency_ms=round(latency, 2),
                detail=f"{used_pct:.1f}% used",
            )
        except Exception as exc:
            return ComponentHealth(
                name="memory",
                status=HealthStatus.healthy,
                detail=f"unable to check: {exc}",
            )

    async def check_disk(self) -> ComponentHealth:
        """Check disk free space using :func:`shutil.disk_usage`."""
        try:
            start = time.monotonic()
            usage = shutil.disk_usage(os.getcwd())
            latency = (time.monotonic() - start) * 1000

            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            used_pct = (usage.used / usage.total) * 100 if usage.total else 0

            if free_gb > 5:
                status = HealthStatus.healthy
            elif free_gb > 1:
                status = HealthStatus.degraded
            else:
                status = HealthStatus.unhealthy

            return ComponentHealth(
                name="disk",
                status=status,
                latency_ms=round(latency, 2),
                detail=f"{free_gb:.1f} GB free / {total_gb:.1f} GB total ({used_pct:.1f}% used)",
            )
        except Exception as exc:
            return ComponentHealth(
                name="disk",
                status=HealthStatus.healthy,
                detail=f"unable to check: {exc}",
            )

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    async def check_all(self) -> dict[str, Any]:
        """Run every check and return a summary dict.

        Returns::

            {
                "status": "healthy" | "degraded" | "unhealthy",
                "components": { "<name>": { ... }, ... },
                "timestamp": "<ISO 8601>",
            }
        """
        tasks: list[asyncio.Task] = []

        # Database
        tasks.append(asyncio.ensure_future(self._safe_check(self.check_database())))

        # LLM providers
        for provider in self._providers:
            tasks.append(asyncio.ensure_future(
                self._safe_check(self.check_llm_provider(provider)),
            ))

        # MCP
        tasks.append(asyncio.ensure_future(self._safe_check(self.check_mcp_servers())))

        # Memory
        tasks.append(asyncio.ensure_future(self._safe_check(self.check_memory())))

        # Disk
        tasks.append(asyncio.ensure_future(self._safe_check(self.check_disk())))

        results: list[ComponentHealth] = await asyncio.gather(*tasks)

        # Build component map
        components: dict[str, dict] = {}
        for r in results:
            components[r.name] = {
                "status": r.status.value,
                "latency_ms": r.latency_ms,
                "detail": r.detail,
            }

        # Overall status: unhealthy > degraded > healthy
        overall = HealthStatus.healthy
        for r in results:
            if r.status == HealthStatus.unhealthy:
                overall = HealthStatus.unhealthy
                break
            if r.status == HealthStatus.degraded:
                overall = HealthStatus.degraded

        return {
            "status": overall.value,
            "components": components,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_check(self, coro) -> ComponentHealth:
        """Wrap a check coroutine so it never raises."""
        try:
            return await coro
        except Exception as exc:
            logger.warning("Health check failed unexpectedly: %s", exc)
            return ComponentHealth(
                name="unknown",
                status=HealthStatus.unhealthy,
                detail=str(exc)[:120],
            )

    @staticmethod
    async def _read_linux_memory() -> dict:
        """Parse ``/proc/meminfo`` for memory usage."""
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    value = int(parts[1])  # kB
                    info[key] = value

        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", 0)
        if total > 0:
            used_pct = ((total - available) / total) * 100
        else:
            used_pct = 0.0
        return {"used_percent": used_pct}

    @staticmethod
    async def _read_macos_memory() -> dict:
        """Use ``vm_stat`` on macOS."""
        proc = await asyncio.create_subprocess_exec(
            "vm_stat",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()

        page_size = 4096  # default
        stats: dict[str, int] = {}
        for line in lines:
            if "page size" in line.lower():
                parts = line.split()
                for p in parts:
                    if p.isdigit():
                        page_size = int(p)
            elif ":" in line:
                key, _, val = line.partition(":")
                val = val.strip().rstrip(".")
                if val.isdigit():
                    stats[key.strip()] = int(val)

        free = stats.get("Pages free", 0) * page_size
        active = stats.get("Pages active", 0) * page_size
        inactive = stats.get("Pages inactive", 0) * page_size
        speculative = stats.get("Pages speculative", 0) * page_size
        wired = stats.get("Pages wired down", 0) * page_size

        total = free + active + inactive + speculative + wired
        used = active + wired
        used_pct = (used / total) * 100 if total else 0.0
        return {"used_percent": used_pct}

    @staticmethod
    async def _read_windows_memory() -> dict:
        """Use ``wmic`` (available on Windows) to read memory info."""
        proc = await asyncio.create_subprocess_exec(
            "wmic", "OS", "get",
            "FreePhysicalMemory,TotalVisibleMemorySize",
            "/value",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        text = stdout.decode(errors="replace")

        values: dict[str, int] = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                val = val.strip()
                if val.isdigit():
                    values[key.strip()] = int(val)

        total_kb = values.get("TotalVisibleMemorySize", 0)
        free_kb = values.get("FreePhysicalMemory", 0)
        if total_kb > 0:
            used_pct = ((total_kb - free_kb) / total_kb) * 100
        else:
            used_pct = 0.0
        return {"used_percent": used_pct}
