"""OutputLimiter 단위 테스트."""
from __future__ import annotations

from breadmind.core.protocols import ToolResult
from breadmind.plugins.builtin.tools.output_limiter import OutputLimiter, OutputLimitConfig


class TestLimit:
    def test_short_output_unchanged(self):
        limiter = OutputLimiter(OutputLimitConfig(max_chars=100))
        result = limiter.limit("hello world")
        assert result == "hello world"

    def test_exact_max_chars_unchanged(self):
        limiter = OutputLimiter(OutputLimitConfig(max_chars=10))
        result = limiter.limit("a" * 10)
        assert result == "a" * 10

    def test_long_output_truncated(self):
        limiter = OutputLimiter(OutputLimitConfig(max_chars=20))
        original = "x" * 100
        result = limiter.limit(original)

        assert result.startswith("x" * 20)
        assert "output truncated" in result
        assert "100 chars" in result
        assert "20 chars" in result

    def test_custom_truncation_message(self):
        config = OutputLimitConfig(
            max_chars=10,
            truncation_message=" [CUT:{original}->{limited}]",
        )
        limiter = OutputLimiter(config)
        result = limiter.limit("a" * 50)
        assert result.endswith("[CUT:50->10]")


class TestLimitToolResult:
    def test_short_result_unchanged(self):
        limiter = OutputLimiter(OutputLimitConfig(max_chars=1000))
        original = ToolResult(success=True, output="short output")
        result = limiter.limit_tool_result(original)
        assert result is original  # same object

    def test_long_result_truncated(self):
        limiter = OutputLimiter(OutputLimitConfig(max_chars=20))
        original = ToolResult(success=True, output="y" * 100)
        result = limiter.limit_tool_result(original)

        assert result is not original
        assert result.success is True
        assert result.error is None
        assert len(result.output) < len(original.output)
        assert "output truncated" in result.output

    def test_error_result_preserved(self):
        limiter = OutputLimiter(OutputLimitConfig(max_chars=20))
        original = ToolResult(success=False, output="z" * 100, error="some error")
        result = limiter.limit_tool_result(original)

        assert result.success is False
        assert result.error == "some error"
        assert "output truncated" in result.output


class TestDefaultConfig:
    def test_default_max_chars(self):
        config = OutputLimitConfig()
        assert config.max_chars == 50_000

    def test_limiter_none_means_no_limit(self):
        """OutputLimiter가 None이면 MessageLoopAgent에서 제한 없이 통과."""
        # This tests the contract: if output_limiter is None, no limiting happens.
        # The actual check is in MessageLoopAgent, so we just verify
        # OutputLimiter itself works standalone.
        limiter = OutputLimiter()
        big_output = "x" * 40_000
        assert limiter.limit(big_output) == big_output
