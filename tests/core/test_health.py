"""Tests for the deep health check system."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.core.health import (
    CHECK_TIMEOUT_SECONDS,
    ComponentHealth,
    HealthChecker,
    HealthStatus,
)


# ------------------------------------------------------------------
# HealthStatus enum
# ------------------------------------------------------------------

def test_health_status_enum():
    """Enum has the three expected values."""
    assert HealthStatus.healthy.value == "healthy"
    assert HealthStatus.degraded.value == "degraded"
    assert HealthStatus.unhealthy.value == "unhealthy"
    assert len(HealthStatus) == 3


# ------------------------------------------------------------------
# Database checks
# ------------------------------------------------------------------

async def test_check_database_healthy():
    """DB returns healthy when health_check() succeeds."""
    db = AsyncMock()
    db.health_check.return_value = True

    checker = HealthChecker(db=db)
    result = await checker.check_database()

    assert result.name == "database"
    assert result.status == HealthStatus.healthy
    assert result.latency_ms > 0
    assert result.detail == "connected"


async def test_check_database_unhealthy():
    """DB returns unhealthy when health_check() raises."""
    db = AsyncMock()
    db.health_check.side_effect = ConnectionError("connection refused")

    checker = HealthChecker(db=db)
    result = await checker.check_database()

    assert result.name == "database"
    assert result.status == HealthStatus.unhealthy
    assert "connection refused" in (result.detail or "")


async def test_check_database_no_db():
    """When no DB is configured, report healthy."""
    checker = HealthChecker(db=None)
    result = await checker.check_database()

    assert result.status == HealthStatus.healthy
    assert "no database" in (result.detail or "").lower()


async def test_check_database_returns_false():
    """DB returns unhealthy when health_check() returns False."""
    db = AsyncMock()
    db.health_check.return_value = False

    checker = HealthChecker(db=db)
    result = await checker.check_database()

    assert result.status == HealthStatus.unhealthy


# ------------------------------------------------------------------
# Memory check
# ------------------------------------------------------------------

async def test_check_memory():
    """Memory check runs without error and returns a valid result."""
    checker = HealthChecker()
    result = await checker.check_memory()

    assert result.name == "memory"
    assert result.status in (HealthStatus.healthy, HealthStatus.degraded, HealthStatus.unhealthy)
    # Should have some detail string
    assert result.detail is not None


# ------------------------------------------------------------------
# Disk check
# ------------------------------------------------------------------

async def test_check_disk():
    """Disk check runs without error and returns a valid result."""
    checker = HealthChecker()
    result = await checker.check_disk()

    assert result.name == "disk"
    assert result.status in (HealthStatus.healthy, HealthStatus.degraded, HealthStatus.unhealthy)
    assert "GB" in (result.detail or "")


# ------------------------------------------------------------------
# LLM provider check
# ------------------------------------------------------------------

async def test_check_llm_provider_healthy():
    """Provider with passing health_check is healthy."""
    provider = AsyncMock()
    provider.name = "test-provider"
    provider.health_check.return_value = True

    checker = HealthChecker()
    result = await checker.check_llm_provider(provider)

    assert result.status == HealthStatus.healthy
    assert "test-provider" in result.name


async def test_check_llm_provider_no_health_method():
    """Provider without health_check is assumed healthy (skipped)."""
    provider = MagicMock(spec=[])
    provider.name = "no-health"

    checker = HealthChecker()
    result = await checker.check_llm_provider(provider)

    assert result.status == HealthStatus.healthy
    assert "skipped" in (result.detail or "")


async def test_check_llm_provider_unhealthy():
    """Provider whose health_check returns False is unhealthy."""
    provider = AsyncMock()
    provider.name = "bad-provider"
    provider.health_check.return_value = False

    checker = HealthChecker()
    result = await checker.check_llm_provider(provider)

    assert result.status == HealthStatus.unhealthy


# ------------------------------------------------------------------
# MCP check
# ------------------------------------------------------------------

async def test_check_mcp_no_manager():
    """No MCP manager -> healthy."""
    checker = HealthChecker(mcp_manager=None)
    result = await checker.check_mcp_servers()

    assert result.status == HealthStatus.healthy


async def test_check_mcp_all_healthy():
    """All MCP servers healthy."""
    srv1 = MagicMock()
    srv1.name = "srv1"
    srv2 = MagicMock()
    srv2.name = "srv2"

    mgr = AsyncMock()
    mgr.list_servers.return_value = [srv1, srv2]
    mgr.health_check.return_value = True

    checker = HealthChecker(mcp_manager=mgr)
    result = await checker.check_mcp_servers()

    assert result.status == HealthStatus.healthy
    assert "2/2" in (result.detail or "")


# ------------------------------------------------------------------
# check_all aggregation
# ------------------------------------------------------------------

async def test_check_all_healthy():
    """All components healthy => overall healthy."""
    checker = HealthChecker(db=None, providers=[], mcp_manager=None)
    result = await checker.check_all()

    assert result["status"] == "healthy"
    assert "components" in result
    assert "timestamp" in result
    # At least database, mcp, memory, disk
    assert len(result["components"]) >= 4


async def test_check_all_degraded():
    """One degraded component => overall degraded."""
    checker = HealthChecker(db=None, providers=[], mcp_manager=None)

    # Monkey-patch disk check to return degraded
    async def fake_disk():
        return ComponentHealth(
            name="disk", status=HealthStatus.degraded,
            latency_ms=1.0, detail="2.0 GB free (low)",
        )
    checker.check_disk = fake_disk

    result = await checker.check_all()
    assert result["status"] == "degraded"


async def test_check_all_unhealthy():
    """One unhealthy component => overall unhealthy."""
    db = AsyncMock()
    db.health_check.side_effect = ConnectionError("down")

    checker = HealthChecker(db=db, providers=[], mcp_manager=None)
    result = await checker.check_all()

    assert result["status"] == "unhealthy"
    assert result["components"]["database"]["status"] == "unhealthy"


# ------------------------------------------------------------------
# Timeout
# ------------------------------------------------------------------

async def test_check_timeout():
    """A check that exceeds the timeout returns unhealthy."""
    db = AsyncMock()

    async def slow_health_check():
        await asyncio.sleep(10)
        return True

    db.health_check = slow_health_check

    checker = HealthChecker(db=db, timeout=0.1)
    result = await checker.check_database()

    assert result.status == HealthStatus.unhealthy
    assert result.detail == "timeout"
