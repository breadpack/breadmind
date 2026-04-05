"""Tests for LLM retry with exponential backoff."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from breadmind.llm.retry import (
    RetryConfig,
    _calculate_delay,
    _is_transient_error,
    retry_with_backoff,
    retry_with_backoff_stream,
)


# ---------------------------------------------------------------------------
# Helpers: fake exceptions with status_code attribute
# ---------------------------------------------------------------------------

class FakeHTTPError(Exception):
    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# test_retry_config_defaults
# ---------------------------------------------------------------------------

class TestRetryConfigDefaults:
    def test_default_values(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.exponential_base == 2.0

    def test_custom_values(self):
        cfg = RetryConfig(max_retries=5, base_delay=0.5, max_delay=30.0, exponential_base=3.0)
        assert cfg.max_retries == 5
        assert cfg.base_delay == 0.5
        assert cfg.max_delay == 30.0
        assert cfg.exponential_base == 3.0


# ---------------------------------------------------------------------------
# test_retry_on_transient_error
# ---------------------------------------------------------------------------

class TestRetryOnTransientError:
    async def test_retry_on_429_then_success(self):
        """429 에러 후 성공하면 결과를 반환해야 한다."""
        call_count = 0

        async def flaky_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeHTTPError(429, "Rate limited")
            return "success"

        config = RetryConfig(max_retries=3, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky_call, config=config)

        assert result == "success"
        assert call_count == 2

    async def test_retry_on_500_then_success(self):
        """500 서버 에러도 재시도되어야 한다."""
        call_count = 0

        async def flaky_call():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise FakeHTTPError(500, "Internal Server Error")
            return "ok"

        config = RetryConfig(max_retries=3, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky_call, config=config)

        assert result == "ok"
        assert call_count == 3

    async def test_retry_on_502(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeHTTPError(502, "Bad Gateway")
            return "done"

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky, config=config)
        assert result == "done"

    async def test_retry_on_503(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeHTTPError(503, "Service Unavailable")
            return "done"

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky, config=config)
        assert result == "done"

    async def test_retry_on_529(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeHTTPError(529, "Overloaded")
            return "done"

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky, config=config)
        assert result == "done"

    async def test_retry_on_connection_error(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection refused")
            return "connected"

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky, config=config)
        assert result == "connected"

    async def test_retry_on_timeout_error(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Timed out")
            return "ok"

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await retry_with_backoff(flaky, config=config)
        assert result == "ok"


# ---------------------------------------------------------------------------
# test_no_retry_on_permanent_error
# ---------------------------------------------------------------------------

class TestNoRetryOnPermanentError:
    async def test_400_raises_immediately(self):
        """400 Bad Request는 재시도하지 않아야 한다."""
        call_count = 0

        async def bad_request():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(400, "Bad Request")

        config = RetryConfig(max_retries=3, base_delay=0.0)
        with pytest.raises(FakeHTTPError, match="Bad Request"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                await retry_with_backoff(bad_request, config=config)

        assert call_count == 1

    async def test_401_raises_immediately(self):
        """401 Unauthorized는 재시도하지 않아야 한다."""
        call_count = 0

        async def unauthorized():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(401, "Unauthorized")

        config = RetryConfig(max_retries=3, base_delay=0.0)
        with pytest.raises(FakeHTTPError, match="Unauthorized"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                await retry_with_backoff(unauthorized, config=config)

        assert call_count == 1

    async def test_403_raises_immediately(self):
        call_count = 0

        async def forbidden():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(403, "Forbidden")

        config = RetryConfig(max_retries=3, base_delay=0.0)
        with pytest.raises(FakeHTTPError):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                await retry_with_backoff(forbidden, config=config)
        assert call_count == 1

    async def test_generic_exception_not_retried(self):
        """status_code가 없는 일반 Exception은 재시도하지 않는다."""
        call_count = 0

        async def generic_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Something went wrong")

        config = RetryConfig(max_retries=3, base_delay=0.0)
        with pytest.raises(ValueError, match="Something went wrong"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                await retry_with_backoff(generic_fail, config=config)
        assert call_count == 1


# ---------------------------------------------------------------------------
# test_max_retries_exceeded
# ---------------------------------------------------------------------------

class TestMaxRetriesExceeded:
    async def test_raises_last_error_after_exhaustion(self):
        """재시도 초과 시 마지막 에러를 raise해야 한다."""
        call_count = 0

        async def always_429():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(429, f"Rate limited (call {call_count})")

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with pytest.raises(FakeHTTPError, match="Rate limited"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                await retry_with_backoff(always_429, config=config)

        # 1 initial + 2 retries = 3 total calls
        assert call_count == 3

    async def test_max_retries_zero_no_retry(self):
        """max_retries=0이면 재시도 없이 첫 시도만 한다."""
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(500, "Server Error")

        config = RetryConfig(max_retries=0, base_delay=0.0)
        with pytest.raises(FakeHTTPError):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                await retry_with_backoff(always_fail, config=config)
        assert call_count == 1


# ---------------------------------------------------------------------------
# test_exponential_backoff_timing
# ---------------------------------------------------------------------------

class TestExponentialBackoffTiming:
    async def test_delays_increase_exponentially(self):
        """백오프 딜레이가 지수적으로 증가하는지 확인한다."""
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float):
            sleep_calls.append(delay)

        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(429, "Rate limited")

        config = RetryConfig(max_retries=3, base_delay=1.0, exponential_base=2.0)

        with patch("breadmind.llm.retry.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(FakeHTTPError):
                await retry_with_backoff(always_fail, config=config)

        assert len(sleep_calls) == 3
        # With jitter, delays should be in range [0, base * exp_base^attempt]
        # attempt 0: [0, 1.0], attempt 1: [0, 2.0], attempt 2: [0, 4.0]
        assert 0.0 <= sleep_calls[0] <= 1.0
        assert 0.0 <= sleep_calls[1] <= 2.0
        assert 0.0 <= sleep_calls[2] <= 4.0

    async def test_max_delay_cap(self):
        """max_delay를 초과하는 딜레이는 max_delay로 제한되어야 한다."""
        config = RetryConfig(base_delay=10.0, max_delay=5.0, exponential_base=2.0)
        # attempt 0: base_delay * 2^0 = 10.0, capped to 5.0
        delay = _calculate_delay(0, config)
        assert 0.0 <= delay <= 5.0


# ---------------------------------------------------------------------------
# test_jitter_applied
# ---------------------------------------------------------------------------

class TestJitterApplied:
    def test_jitter_varies_delays(self):
        """동일한 설정으로 여러 번 호출하면 다른 딜레이 값이 나와야 한다."""
        config = RetryConfig(base_delay=1.0, exponential_base=2.0)
        delays = [_calculate_delay(2, config) for _ in range(100)]

        # With jitter over 100 samples, we should see variation
        unique_delays = set(delays)
        assert len(unique_delays) > 1, "Jitter should produce varying delays"

        # All delays should be in valid range [0, base * exp^attempt]
        max_possible = config.base_delay * (config.exponential_base ** 2)
        for d in delays:
            assert 0.0 <= d <= max_possible

    def test_jitter_bounded(self):
        """딜레이는 항상 0 이상이고 최대값 이하여야 한다."""
        config = RetryConfig(base_delay=2.0, max_delay=10.0, exponential_base=3.0)
        for attempt in range(10):
            delay = _calculate_delay(attempt, config)
            expected_max = min(
                config.base_delay * (config.exponential_base ** attempt),
                config.max_delay,
            )
            assert 0.0 <= delay <= expected_max


# ---------------------------------------------------------------------------
# test_retry_with_stream
# ---------------------------------------------------------------------------

class TestRetryWithStream:
    async def test_stream_retry_on_transient_error(self):
        """스트리밍에서 transient 에러 발생 시 재시도해야 한다."""
        call_count = 0

        async def flaky_stream() -> AsyncGenerator[str, None]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FakeHTTPError(429, "Rate limited")
            yield "hello "
            yield "world"

        config = RetryConfig(max_retries=2, base_delay=0.0)
        chunks: list[str] = []
        with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
            async for chunk in retry_with_backoff_stream(flaky_stream, config=config):
                chunks.append(chunk)

        assert chunks == ["hello ", "world"]
        assert call_count == 2

    async def test_stream_no_retry_on_permanent_error(self):
        """스트리밍에서 permanent 에러는 즉시 raise한다."""
        call_count = 0

        async def bad_stream() -> AsyncGenerator[str, None]:
            nonlocal call_count
            call_count += 1
            raise FakeHTTPError(401, "Unauthorized")
            yield  # Make it a generator  # noqa: E501

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with pytest.raises(FakeHTTPError, match="Unauthorized"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                async for _ in retry_with_backoff_stream(bad_stream, config=config):
                    pass
        assert call_count == 1

    async def test_stream_no_retry_after_yielding(self):
        """이미 데이터를 yield한 후 에러가 발생하면 재시도하지 않는다."""
        call_count = 0

        async def partial_stream() -> AsyncGenerator[str, None]:
            nonlocal call_count
            call_count += 1
            yield "partial"
            raise FakeHTTPError(500, "Server Error mid-stream")

        config = RetryConfig(max_retries=2, base_delay=0.0)
        chunks: list[str] = []
        with pytest.raises(FakeHTTPError, match="Server Error mid-stream"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                async for chunk in retry_with_backoff_stream(
                    partial_stream, config=config
                ):
                    chunks.append(chunk)

        assert chunks == ["partial"]
        assert call_count == 1  # No retry because data was already yielded

    async def test_stream_max_retries_exceeded(self):
        """스트리밍에서 재시도 초과 시 마지막 에러를 raise한다."""
        call_count = 0

        async def always_fail_stream() -> AsyncGenerator[str, None]:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Connection refused")
            yield  # noqa: E501

        config = RetryConfig(max_retries=2, base_delay=0.0)
        with pytest.raises(ConnectionError, match="Connection refused"):
            with patch("breadmind.llm.retry.asyncio.sleep", new_callable=AsyncMock):
                async for _ in retry_with_backoff_stream(
                    always_fail_stream, config=config
                ):
                    pass

        assert call_count == 3  # 1 initial + 2 retries


# ---------------------------------------------------------------------------
# test_is_transient_error
# ---------------------------------------------------------------------------

class TestIsTransientError:
    def test_connection_error_is_transient(self):
        assert _is_transient_error(ConnectionError()) is True

    def test_timeout_error_is_transient(self):
        assert _is_transient_error(TimeoutError()) is True

    def test_429_is_transient(self):
        assert _is_transient_error(FakeHTTPError(429)) is True

    def test_500_is_transient(self):
        assert _is_transient_error(FakeHTTPError(500)) is True

    def test_502_is_transient(self):
        assert _is_transient_error(FakeHTTPError(502)) is True

    def test_503_is_transient(self):
        assert _is_transient_error(FakeHTTPError(503)) is True

    def test_529_is_transient(self):
        assert _is_transient_error(FakeHTTPError(529)) is True

    def test_400_is_not_transient(self):
        assert _is_transient_error(FakeHTTPError(400)) is False

    def test_401_is_not_transient(self):
        assert _is_transient_error(FakeHTTPError(401)) is False

    def test_403_is_not_transient(self):
        assert _is_transient_error(FakeHTTPError(403)) is False

    def test_404_is_not_transient(self):
        assert _is_transient_error(FakeHTTPError(404)) is False

    def test_generic_exception_not_transient(self):
        assert _is_transient_error(ValueError("nope")) is False
