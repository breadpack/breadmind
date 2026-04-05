"""TokenCounter 및 AutoCompactor 연동 테스트."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from breadmind.core.token_counter import (
    MODEL_CONTEXT_LIMITS,
    TokenCounter,
    get_context_limit,
)
from breadmind.core.protocols import Message


# ---------------------------------------------------------------------------
# TokenCounter 단위 테스트
# ---------------------------------------------------------------------------


class TestTokenCounterWithTiktoken:
    """tiktoken이 설치된 환경에서의 테스트."""

    def test_count_basic_english(self) -> None:
        counter = TokenCounter(model="claude-sonnet-4-6")
        if not counter.has_tiktoken:
            pytest.skip("tiktoken not installed")
        tokens = counter.count("Hello, world!")
        # cl100k_base에서 "Hello, world!" → 4 토큰
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_count_cjk(self) -> None:
        counter = TokenCounter(model="claude-sonnet-4-6")
        if not counter.has_tiktoken:
            pytest.skip("tiktoken not installed")
        tokens = counter.count("안녕하세요 세계")
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_count_empty_string(self) -> None:
        counter = TokenCounter()
        assert counter.count("") == 0

    def test_count_messages(self) -> None:
        counter = TokenCounter()
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
            Message(role="user", content=None),
        ]
        total = counter.count_messages(messages)
        assert isinstance(total, int)
        assert total > 0


class TestTokenCounterFallback:
    """tiktoken 미설치 시 fallback 동작 테스트."""

    def test_fallback_without_tiktoken(self) -> None:
        with patch.dict("sys.modules", {"tiktoken": None}):
            # 새 인스턴스가 tiktoken import 실패하도록 강제
            counter = TokenCounter.__new__(TokenCounter)
            counter.model = "claude-sonnet-4-6"
            counter._encoding = None
            counter._use_tiktoken = False

            assert not counter.has_tiktoken
            # fallback: len("abcdefgh") // 4 == 2
            assert counter.count("abcdefgh") == 2

    def test_fallback_empty_string(self) -> None:
        counter = TokenCounter.__new__(TokenCounter)
        counter.model = "claude-sonnet-4-6"
        counter._encoding = None
        counter._use_tiktoken = False

        assert counter.count("") == 0

    def test_fallback_count_messages(self) -> None:
        counter = TokenCounter.__new__(TokenCounter)
        counter.model = "claude-sonnet-4-6"
        counter._encoding = None
        counter._use_tiktoken = False

        messages = [
            Message(role="user", content="a" * 100),  # 25 tokens
            Message(role="assistant", content="b" * 40),  # 10 tokens
        ]
        assert counter.count_messages(messages) == 35


# ---------------------------------------------------------------------------
# MODEL_CONTEXT_LIMITS / get_context_limit 테스트
# ---------------------------------------------------------------------------


class TestModelContextLimits:
    def test_model_context_limits(self) -> None:
        assert MODEL_CONTEXT_LIMITS["claude-opus-4-6"] == 1_000_000
        assert MODEL_CONTEXT_LIMITS["claude-sonnet-4-6"] == 200_000
        assert MODEL_CONTEXT_LIMITS["claude-haiku-4-5"] == 200_000
        assert MODEL_CONTEXT_LIMITS["gemini-2.5-pro"] == 1_000_000
        assert MODEL_CONTEXT_LIMITS["gemini-2.5-flash"] == 1_000_000
        assert MODEL_CONTEXT_LIMITS["grok-3"] == 131_072

    def test_get_context_limit_known_model(self) -> None:
        assert get_context_limit("claude-opus-4-6") == 1_000_000

    def test_get_context_limit_unknown_model(self) -> None:
        limit = get_context_limit("unknown-model-xyz")
        assert limit == 128_000  # default


# ---------------------------------------------------------------------------
# AutoCompactor 연동 테스트
# ---------------------------------------------------------------------------


class TestAutoCompactorWithTokenCounter:
    def test_auto_compactor_with_token_counter(self) -> None:
        from breadmind.plugins.builtin.agent_loop.auto_compact import (
            AutoCompactor,
            CompactConfig,
        )

        # mock provider
        provider = MagicMock()

        # mock token counter
        token_counter = MagicMock()
        token_counter.count_messages.return_value = 42

        compactor = AutoCompactor(
            provider=provider,
            config=CompactConfig(),
            token_counter=token_counter,
        )

        messages = [Message(role="user", content="test")]
        result = compactor.estimate_tokens(messages)

        assert result == 42
        token_counter.count_messages.assert_called_once_with(messages)

    def test_auto_compactor_without_token_counter(self) -> None:
        from breadmind.plugins.builtin.agent_loop.auto_compact import (
            AutoCompactor,
            CompactConfig,
        )

        provider = MagicMock()
        compactor = AutoCompactor(provider=provider, config=CompactConfig())

        messages = [Message(role="user", content="a" * 100)]
        result = compactor.estimate_tokens(messages)

        # fallback: 100 // 4 == 25
        assert result == 25
