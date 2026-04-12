"""Circuit Breaker pattern for external service calls.

Prevents cascading failures by stopping calls to unhealthy services
and allowing them to recover before retrying.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation — calls pass through
    OPEN = "open"  # Failure threshold reached — calls rejected
    HALF_OPEN = "half_open"  # Recovery probe — limited calls allowed


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is open."""

    def __init__(self, name: str, remaining_seconds: float) -> None:
        self.name = name
        self.remaining_seconds = remaining_seconds
        super().__init__(
            f"Circuit '{name}' is OPEN. "
            f"Recovery in {remaining_seconds:.1f}s."
        )


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1
    success_threshold: int = 2


class CircuitBreaker:
    """Async-safe circuit breaker for a single service."""

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self.name = name
        self._config = config or CircuitBreakerConfig()
        self._lock = asyncio.Lock()

        # Internal mutable state
        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._half_open_calls: int = 0
        self._last_failure_time: float | None = None
        self._opened_at: float | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state.

        Automatically transitions OPEN -> HALF_OPEN when the recovery
        timeout has elapsed (checked without acquiring the lock so that
        callers can inspect state cheaply).
        """
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._config.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._config

    # ------------------------------------------------------------------
    # Core call wrapper
    # ------------------------------------------------------------------

    async def call(self, coro: Coroutine[Any, Any, T]) -> T:
        """Execute *coro* through the circuit breaker.

        Raises:
            CircuitOpenError: If the circuit is OPEN and recovery timeout
                has not yet elapsed.
        """
        async with self._lock:
            effective_state = self._effective_state()

            if effective_state is CircuitState.OPEN:
                remaining = self._remaining_recovery_time()
                await self._close_coro(coro)
                raise CircuitOpenError(self.name, remaining)

            if effective_state is CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    remaining = self._remaining_recovery_time()
                    await self._close_coro(coro)
                    raise CircuitOpenError(self.name, remaining)
                self._half_open_calls += 1

        # Execute outside the lock so the coroutine can run freely.
        try:
            result = await coro
        except Exception:
            async with self._lock:
                self._record_failure()
            raise

        async with self._lock:
            self._record_success()
        return result

    # ------------------------------------------------------------------
    # Manual reset
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        async with self._lock:
            self._transition_to_closed()
            logger.info("Circuit '%s' manually reset to CLOSED.", self.name)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return a snapshot of the circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "config": {
                "failure_threshold": self._config.failure_threshold,
                "recovery_timeout": self._config.recovery_timeout,
                "half_open_max_calls": self._config.half_open_max_calls,
                "success_threshold": self._config.success_threshold,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _effective_state(self) -> CircuitState:
        """Compute the effective state, promoting OPEN -> HALF_OPEN if due."""
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.info(
                    "Circuit '%s' transitioned OPEN -> HALF_OPEN after %.1fs.",
                    self.name,
                    elapsed,
                )
        return self._state

    def _record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        self._success_count = 0

        if self._state is CircuitState.HALF_OPEN:
            self._transition_to_open()
            logger.warning(
                "Circuit '%s' HALF_OPEN -> OPEN after failure.",
                self.name,
            )
        elif (
            self._state is CircuitState.CLOSED
            and self._failure_count >= self._config.failure_threshold
        ):
            self._transition_to_open()
            logger.warning(
                "Circuit '%s' CLOSED -> OPEN after %d failures.",
                self.name,
                self._failure_count,
            )

    def _record_success(self) -> None:
        """Record a success and potentially close the circuit."""
        if self._state is CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._transition_to_closed()
                logger.info(
                    "Circuit '%s' HALF_OPEN -> CLOSED after %d successes.",
                    self.name,
                    self._success_count,
                )
        elif self._state is CircuitState.CLOSED:
            # Reset failure count on success in closed state
            self._failure_count = 0

    def _transition_to_open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._half_open_calls = 0
        self._success_count = 0

    def _transition_to_closed(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._opened_at = None

    def _remaining_recovery_time(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = time.monotonic() - self._opened_at
        return max(0.0, self._config.recovery_timeout - elapsed)

    @staticmethod
    async def _close_coro(coro: Coroutine[Any, Any, Any]) -> None:
        """Close an unawaited coroutine to prevent RuntimeWarning."""
        coro.close()


class CircuitBreakerRegistry:
    """Registry for managing named circuit breakers."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get an existing circuit breaker or create a new one."""
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config)
                logger.debug("Created circuit breaker '%s'.", name)
            return self._breakers[name]

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Return statistics for every registered circuit breaker."""
        return {name: cb.get_stats() for name, cb in self._breakers.items()}
