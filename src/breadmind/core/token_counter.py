"""Tiktoken 기반 정확한 토큰 카운팅 (graceful fallback 포함)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from breadmind.core.protocols import Message

logger = logging.getLogger(__name__)

# 모델별 최대 컨텍스트 윈도우 (토큰)
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "grok-3": 131_072,
}

_DEFAULT_CONTEXT_LIMIT = 128_000


def get_context_limit(model: str) -> int:
    """모델별 최대 컨텍스트 윈도우를 반환한다.

    등록되지 않은 모델은 기본값(128,000)을 반환한다.
    """
    return MODEL_CONTEXT_LIMITS.get(model, _DEFAULT_CONTEXT_LIMIT)


class TokenCounter:
    """tiktoken 기반 토큰 카운터.

    tiktoken이 설치되어 있으면 cl100k_base 인코딩을 사용하고,
    없으면 ``len(text) // 4`` fallback을 사용한다.
    """

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model
        self._encoding: Any | None = None
        self._use_tiktoken = False

        try:
            import tiktoken  # noqa: F811

            # Claude / Gemini / Grok 모두 cl100k_base로 근사
            self._encoding = tiktoken.get_encoding("cl100k_base")
            self._use_tiktoken = True
            logger.debug("TokenCounter: tiktoken cl100k_base 인코딩 사용")
        except ImportError:
            logger.debug("TokenCounter: tiktoken 미설치, chars/4 fallback 사용")

    @property
    def has_tiktoken(self) -> bool:
        """tiktoken 사용 가능 여부."""
        return self._use_tiktoken

    def count(self, text: str) -> int:
        """텍스트의 토큰 수를 반환한다."""
        if not text:
            return 0
        if self._use_tiktoken and self._encoding is not None:
            return len(self._encoding.encode(text))
        # fallback: 문자수 / 4
        return len(text) // 4

    def count_messages(self, messages: list[Message]) -> int:
        """메시지 리스트의 총 토큰 수를 반환한다."""
        total = 0
        for msg in messages:
            total += self.count(msg.content or "")
        return total
