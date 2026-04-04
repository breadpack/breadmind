"""도구 출력 크기 제한 (microcompact)."""
from __future__ import annotations

from dataclasses import dataclass

from breadmind.core.protocols import ToolResult


@dataclass
class OutputLimitConfig:
    """출력 제한 설정."""
    max_chars: int = 50_000         # 도구 출력 최대 문자수
    truncation_message: str = (
        "\n\n... (output truncated, {original} chars -> {limited} chars)"
    )
    summarize_threshold: int = 100_000  # 이 이상이면 요약 시도 (provider 있을 때)


class OutputLimiter:
    """도구 출력이 max_chars를 초과하면 truncate한다."""

    def __init__(self, config: OutputLimitConfig | None = None) -> None:
        self._config = config or OutputLimitConfig()

    def limit(self, output: str) -> str:
        """출력이 max_chars 초과 시 truncate + 메시지 추가."""
        if len(output) <= self._config.max_chars:
            return output

        original_len = len(output)
        truncated = output[: self._config.max_chars]
        suffix = self._config.truncation_message.format(
            original=original_len,
            limited=self._config.max_chars,
        )
        return truncated + suffix

    def limit_tool_result(self, result: ToolResult) -> ToolResult:
        """ToolResult의 output을 제한."""
        limited_output = self.limit(result.output)
        if limited_output is result.output:
            return result
        return ToolResult(
            success=result.success,
            output=limited_output,
            error=result.error,
        )
