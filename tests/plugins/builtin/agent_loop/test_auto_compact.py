"""AutoCompactor 단위 테스트."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from breadmind.core.protocols import LLMResponse, Message, TokenUsage
from breadmind.plugins.builtin.agent_loop.auto_compact import AutoCompactor, CompactConfig


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def _make_provider(summary_text: str = "Summary of old conversation.") -> AsyncMock:
    provider = AsyncMock()
    provider.chat.return_value = LLMResponse(
        content=summary_text,
        tool_calls=[],
        usage=TokenUsage(),
        stop_reason="end_turn",
    )
    return provider


# ── should_compact ────────────────────────────────────────────────


class TestShouldCompact:
    def test_below_threshold_returns_false(self):
        provider = _make_provider()
        config = CompactConfig(max_context_tokens=1000, compact_threshold=0.7)
        compactor = AutoCompactor(provider, config)

        # 100 chars -> ~25 tokens, threshold = 700
        messages = [_msg("user", "x" * 100)]
        assert compactor.should_compact(messages) is False

    def test_above_threshold_returns_true(self):
        provider = _make_provider()
        config = CompactConfig(max_context_tokens=1000, compact_threshold=0.7)
        compactor = AutoCompactor(provider, config)

        # 3000 chars -> ~750 tokens, threshold = 700
        messages = [_msg("user", "x" * 3000)]
        assert compactor.should_compact(messages) is True

    def test_exact_threshold_returns_false(self):
        provider = _make_provider()
        config = CompactConfig(max_context_tokens=1000, compact_threshold=0.7)
        compactor = AutoCompactor(provider, config)

        # 2800 chars -> 700 tokens, threshold = 700 (not exceeded)
        messages = [_msg("user", "x" * 2800)]
        assert compactor.should_compact(messages) is False


# ── compact ───────────────────────────────────────────────────────


class TestCompact:
    @pytest.mark.asyncio
    async def test_preserves_system_message(self):
        provider = _make_provider("Summary.")
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(provider, config)

        messages = [
            _msg("system", "You are helpful."),
            _msg("user", "msg1"),
            _msg("assistant", "resp1"),
            _msg("user", "msg2"),
            _msg("assistant", "resp2"),
        ]
        result = await compactor.compact(messages)

        assert result[0].role == "system"
        assert result[0].content == "You are helpful."

    @pytest.mark.asyncio
    async def test_creates_summary_message(self):
        provider = _make_provider("Old stuff happened.")
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(provider, config)

        messages = [
            _msg("system", "System prompt"),
            _msg("user", "msg1"),
            _msg("assistant", "resp1"),
            _msg("user", "msg2"),
            _msg("assistant", "resp2"),
        ]
        result = await compactor.compact(messages)

        # summary message is second
        assert result[1].role == "system"
        assert "[Previous conversation summary]" in result[1].content
        assert "Old stuff happened." in result[1].content

    @pytest.mark.asyncio
    async def test_keeps_recent_messages(self):
        provider = _make_provider("Summary.")
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(provider, config)

        messages = [
            _msg("system", "System"),
            _msg("user", "old1"),
            _msg("assistant", "old2"),
            _msg("user", "recent1"),
            _msg("assistant", "recent2"),
        ]
        result = await compactor.compact(messages)

        # [system, summary, recent1, recent2]
        assert len(result) == 4
        assert result[2].content == "recent1"
        assert result[3].content == "recent2"

    @pytest.mark.asyncio
    async def test_too_few_messages_returns_original(self):
        provider = _make_provider()
        config = CompactConfig(keep_recent=6)
        compactor = AutoCompactor(provider, config)

        messages = [
            _msg("system", "System"),
            _msg("user", "hello"),
            _msg("assistant", "hi"),
        ]
        result = await compactor.compact(messages)
        assert result is messages  # same object, unchanged

    @pytest.mark.asyncio
    async def test_llm_failure_returns_original(self):
        provider = AsyncMock()
        provider.chat.side_effect = RuntimeError("LLM down")
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(provider, config)

        messages = [
            _msg("system", "System"),
            _msg("user", "msg1"),
            _msg("assistant", "resp1"),
            _msg("user", "msg2"),
            _msg("assistant", "resp2"),
        ]
        result = await compactor.compact(messages)
        assert result is messages  # safety: returns original

    @pytest.mark.asyncio
    async def test_no_system_message(self):
        provider = _make_provider("Summary.")
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(provider, config)

        messages = [
            _msg("user", "old1"),
            _msg("assistant", "old2"),
            _msg("user", "recent1"),
            _msg("assistant", "recent2"),
        ]
        result = await compactor.compact(messages)

        # [summary, recent1, recent2]
        assert len(result) == 3
        assert result[0].role == "system"
        assert "[Previous conversation summary]" in result[0].content


# ── estimate_tokens ───────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_messages(self):
        compactor = AutoCompactor(_make_provider())
        assert compactor.estimate_tokens([]) == 0

    def test_char_based_estimation(self):
        compactor = AutoCompactor(_make_provider())
        messages = [_msg("user", "a" * 400)]
        assert compactor.estimate_tokens(messages) == 100

    def test_none_content(self):
        compactor = AutoCompactor(_make_provider())
        messages = [Message(role="assistant", content=None)]
        assert compactor.estimate_tokens(messages) == 0
