"""LLM call retry with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

if TYPE_CHECKING:
    from breadmind.core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# HTTP status codes considered transient (retriable)
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 529})


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for retry with exponential backoff."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0


def _is_transient_error(error: Exception) -> bool:
    """Determine if an error is transient and should be retried.

    Transient errors:
    - HTTP 429 (rate limit), 500, 502, 503, 529 (server errors)
    - ConnectionError, TimeoutError and their subclasses
    - aiohttp.ClientError (connection-level failures)
    """
    # Connection and timeout errors are always transient
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True

    # Check for aiohttp client errors (connection-level)
    try:
        import aiohttp
        if isinstance(error, aiohttp.ClientError):
            return True
    except ImportError:
        pass

    # Check for HTTP status codes embedded in various exception types
    status_code = _extract_status_code(error)
    if status_code is not None:
        return status_code in _TRANSIENT_STATUS_CODES

    return False


def _extract_status_code(error: Exception) -> int | None:
    """Extract HTTP status code from various exception types."""
    # anthropic exceptions: status_code attribute
    if hasattr(error, "status_code"):
        return error.status_code

    # openai exceptions: status_code attribute
    if hasattr(error, "status_code"):
        return error.status_code

    # Generic: check for 'status' attribute (aiohttp responses, etc.)
    if hasattr(error, "status"):
        return error.status

    return None


def _calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay with exponential backoff and jitter."""
    delay = config.base_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)
    # Apply jitter: random value between 0 and delay
    jitter = random.uniform(0, delay)  # noqa: S311
    return jitter


async def retry_with_backoff(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async function with retry and exponential backoff.

    Only transient errors are retried. Permanent errors (e.g., 400, 401, 403, 404)
    are raised immediately.

    When *circuit_breaker* is provided, each attempt is wrapped in its
    ``call()`` method.  A ``CircuitOpenError`` is **never** retried and
    propagates immediately.

    Args:
        func: Async function to call.
        *args: Positional arguments for func.
        config: Retry configuration. Uses defaults if None.
        circuit_breaker: Optional circuit breaker to guard calls.
        **kwargs: Keyword arguments for func.

    Returns:
        The result of func(*args, **kwargs).

    Raises:
        The last exception if all retries are exhausted.
        CircuitOpenError: If the circuit breaker is open.
    """
    from breadmind.core.circuit_breaker import CircuitOpenError

    cfg = config or RetryConfig()
    last_error: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            coro = func(*args, **kwargs)
            if circuit_breaker is not None:
                return await circuit_breaker.call(coro)
            return await coro
        except CircuitOpenError:
            raise
        except Exception as e:
            if not _is_transient_error(e):
                raise

            last_error = e

            if attempt >= cfg.max_retries:
                break

            delay = _calculate_delay(attempt, cfg)
            logger.warning(
                "Transient error on attempt %d/%d (%s: %s), retrying in %.2fs",
                attempt + 1,
                cfg.max_retries + 1,
                type(e).__name__,
                str(e)[:200],
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]


async def retry_with_backoff_stream(
    func: Callable[..., AsyncGenerator[str, None]],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """Execute a streaming async generator with retry and exponential backoff.

    Retries the entire generator call on transient errors. Once the generator
    has started yielding values, errors are not retried (partial results
    would be duplicated).

    Args:
        func: Async generator function to call.
        *args: Positional arguments for func.
        config: Retry configuration. Uses defaults if None.
        **kwargs: Keyword arguments for func.

    Yields:
        Values from the async generator.

    Raises:
        The last exception if all retries are exhausted.
    """
    cfg = config or RetryConfig()
    last_error: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            started = False
            async for item in func(*args, **kwargs):
                started = True
                yield item
            return  # Completed successfully
        except Exception as e:
            if started:
                # Already yielded data; cannot retry without duplication
                raise

            if not _is_transient_error(e):
                raise

            last_error = e

            if attempt >= cfg.max_retries:
                break

            delay = _calculate_delay(attempt, cfg)
            logger.warning(
                "Transient stream error on attempt %d/%d (%s: %s), retrying in %.2fs",
                attempt + 1,
                cfg.max_retries + 1,
                type(e).__name__,
                str(e)[:200],
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
