"""Tests for the Circuit Breaker implementation."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from breadmind.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _succeed(value: str = "ok") -> str:
    return value


async def _fail(msg: str = "boom") -> str:
    raise ConnectionError(msg)


def _make_cb(
    *,
    failure_threshold: int = 3,
    recovery_timeout: float = 1.0,
    half_open_max_calls: int = 1,
    success_threshold: int = 2,
) -> CircuitBreaker:
    return CircuitBreaker(
        "test",
        CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_max_calls,
            success_threshold=success_threshold,
        ),
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


async def test_closed_state_success():
    """Normal calls pass through in CLOSED state."""
    cb = _make_cb()
    result = await cb.call(_succeed("hello"))
    assert result == "hello"
    assert cb.state is CircuitState.CLOSED


async def test_closed_to_open():
    """Circuit transitions CLOSED -> OPEN after failure_threshold failures."""
    cb = _make_cb(failure_threshold=3)

    for _ in range(3):
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

    assert cb.state is CircuitState.OPEN


async def test_open_rejects_calls():
    """OPEN circuit rejects calls immediately with CircuitOpenError."""
    cb = _make_cb(failure_threshold=2, recovery_timeout=100.0)

    # Trip the breaker
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

    assert cb.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError) as exc_info:
        await cb.call(_succeed())

    assert exc_info.value.name == "test"
    assert exc_info.value.remaining_seconds > 0


async def test_open_to_half_open():
    """Circuit transitions OPEN -> HALF_OPEN after recovery_timeout."""
    cb = _make_cb(failure_threshold=2, recovery_timeout=0.5)

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

    assert cb.state is CircuitState.OPEN

    # Simulate time passing beyond recovery_timeout
    cb._opened_at = time.monotonic() - 1.0

    assert cb.state is CircuitState.HALF_OPEN


async def test_half_open_success_to_closed():
    """Sufficient successes in HALF_OPEN transition back to CLOSED."""
    cb = _make_cb(
        failure_threshold=2,
        recovery_timeout=0.1,
        half_open_max_calls=3,
        success_threshold=2,
    )

    # Trip the breaker
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

    assert cb.state is CircuitState.OPEN

    # Fast-forward past recovery timeout
    cb._opened_at = time.monotonic() - 1.0

    # Two successes should close the circuit
    await cb.call(_succeed())
    await cb.call(_succeed())

    assert cb.state is CircuitState.CLOSED


async def test_half_open_failure_to_open():
    """A failure in HALF_OPEN reopens the circuit."""
    cb = _make_cb(failure_threshold=2, recovery_timeout=0.1)

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

    # Fast-forward past recovery timeout
    cb._opened_at = time.monotonic() - 1.0
    assert cb.state is CircuitState.HALF_OPEN

    with pytest.raises(ConnectionError):
        await cb.call(_fail())

    assert cb.state is CircuitState.OPEN


async def test_reset():
    """Manual reset returns the circuit to CLOSED."""
    cb = _make_cb(failure_threshold=2)

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

    assert cb.state is CircuitState.OPEN

    await cb.reset()
    assert cb.state is CircuitState.CLOSED
    assert cb._failure_count == 0


async def test_get_stats():
    """get_stats returns expected structure and values."""
    cb = _make_cb(failure_threshold=3)

    # One failure
    with pytest.raises(ConnectionError):
        await cb.call(_fail())

    stats = cb.get_stats()
    assert stats["name"] == "test"
    assert stats["state"] == "closed"
    assert stats["failure_count"] == 1
    assert stats["last_failure_time"] is not None
    assert stats["config"]["failure_threshold"] == 3


async def test_circuit_breaker_registry():
    """Registry creates and reuses circuit breakers."""
    registry = CircuitBreakerRegistry()

    cb1 = await registry.get_or_create("service-a")
    cb2 = await registry.get_or_create("service-a")
    cb3 = await registry.get_or_create("service-b")

    assert cb1 is cb2
    assert cb1 is not cb3

    all_stats = registry.get_all_stats()
    assert "service-a" in all_stats
    assert "service-b" in all_stats


async def test_concurrent_access():
    """Circuit breaker is safe under concurrent access via asyncio.Lock."""
    cb = _make_cb(failure_threshold=5, recovery_timeout=100.0)

    async def fail_once() -> None:
        try:
            await cb.call(_fail())
        except (ConnectionError, CircuitOpenError):
            pass

    # Fire 10 concurrent failures — some will get ConnectionError,
    # the rest CircuitOpenError once the breaker trips.
    await asyncio.gather(*[fail_once() for _ in range(10)])

    # Circuit must be OPEN and failure count at least threshold
    assert cb.state is CircuitState.OPEN
    assert cb._failure_count >= 5


async def test_config_defaults():
    """Default config values are correct."""
    cfg = CircuitBreakerConfig()
    assert cfg.failure_threshold == 5
    assert cfg.recovery_timeout == 30.0
    assert cfg.half_open_max_calls == 1
    assert cfg.success_threshold == 2


async def test_integration_with_retry():
    """retry_with_backoff respects circuit breaker."""
    from breadmind.llm.retry import RetryConfig, retry_with_backoff

    cb = _make_cb(failure_threshold=2, recovery_timeout=100.0)

    call_count = 0

    async def flaky() -> str:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("service down")

    # Retry config allows 2 retries (3 total attempts).
    # failure_threshold=2, so 2nd attempt trips the breaker,
    # 3rd attempt raises CircuitOpenError which is not retried.
    retry_cfg = RetryConfig(max_retries=2, base_delay=0.01, max_delay=0.02)

    with pytest.raises(CircuitOpenError):
        await retry_with_backoff(flaky, config=retry_cfg, circuit_breaker=cb)

    assert call_count == 2  # Only 2 actual calls; 3rd was blocked by breaker
    assert cb.state is CircuitState.OPEN

    # Next call should immediately raise CircuitOpenError, no retries
    call_count = 0
    with pytest.raises(CircuitOpenError):
        await retry_with_backoff(flaky, config=retry_cfg, circuit_breaker=cb)

    assert call_count == 0  # No actual calls made
