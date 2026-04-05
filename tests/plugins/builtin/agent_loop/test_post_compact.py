"""Tests for POST_COMPACT hook and compact_instructions in AutoCompactor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from breadmind.core.protocols import LLMResponse, Message, TokenUsage
from breadmind.plugins.builtin.agent_loop.auto_compact import (
    AutoCompactor,
    CompactConfig,
    CompactionLevel,
)


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


# ── POST_COMPACT hook ────────────────────────────────────────────


async def test_post_compact_hook_fires_after_compaction():
    """on_post_compact callback is called after compaction completes."""
    provider = _make_provider()
    post_compact_calls = []

    async def on_post_compact(messages, level):
        post_compact_calls.append({"count": len(messages), "level": level})

    config = CompactConfig(max_context_tokens=100)
    compactor = AutoCompactor(
        provider, config, on_post_compact=on_post_compact,
    )

    # Build enough messages to trigger compaction (0.5 * 100 = 50 token threshold)
    # 300 chars / 4 = 75 tokens -> exceeds level 2 threshold (65)
    messages = [_msg("user", "x" * 300)]
    await compactor.compact(messages)

    assert len(post_compact_calls) == 1
    assert post_compact_calls[0]["level"] >= CompactionLevel.TOOL_RESULT_TRIM


async def test_post_compact_hook_not_fired_when_no_compaction():
    """on_post_compact is NOT called if compaction level is NONE."""
    provider = _make_provider()
    post_compact_calls = []

    compactor = AutoCompactor(
        provider,
        CompactConfig(max_context_tokens=100_000),
        on_post_compact=lambda msgs, lvl: post_compact_calls.append(1),
    )

    messages = [_msg("user", "short")]
    await compactor.compact(messages)
    assert len(post_compact_calls) == 0


async def test_post_compact_hook_sync_callback():
    """Sync on_post_compact callback also works."""
    provider = _make_provider()
    calls = []

    def sync_post(messages, level):
        calls.append(level)

    config = CompactConfig(max_context_tokens=100)
    compactor = AutoCompactor(provider, config, on_post_compact=sync_post)

    messages = [_msg("user", "x" * 300)]
    await compactor.compact(messages)
    assert len(calls) == 1


async def test_post_compact_hook_error_does_not_break_compaction():
    """If on_post_compact raises, compaction still returns results."""
    provider = _make_provider()

    async def bad_hook(messages, level):
        raise RuntimeError("hook exploded")

    config = CompactConfig(max_context_tokens=100)
    compactor = AutoCompactor(provider, config, on_post_compact=bad_hook)

    messages = [_msg("user", "x" * 300)]
    result = await compactor.compact(messages)
    # Should return compacted result despite hook failure
    assert isinstance(result, list)
    assert len(result) > 0


async def test_post_compact_receives_compacted_messages():
    """on_post_compact receives the final compacted messages, not originals."""
    provider = _make_provider("Summarized content.")
    received_messages = []

    async def capture(messages, level):
        received_messages.extend(messages)

    config = CompactConfig(max_context_tokens=100, keep_recent=2)
    compactor = AutoCompactor(
        provider, config, on_post_compact=capture,
    )

    # Force summarize level to get clearly different output
    messages = [
        _msg("system", "You are helpful."),
        _msg("user", "x" * 200),
        _msg("assistant", "y" * 200),
        _msg("user", "z" * 200),
        _msg("assistant", "w" * 200),
    ]
    result = await compactor.compact(messages, force_level=CompactionLevel.SUMMARIZE_OLD)
    assert len(received_messages) > 0
    # The messages the hook received should be the same as the return value
    assert len(received_messages) == len(result)


# ── compact_instructions ─────────────────────────────────────────


async def test_compact_instructions_included_in_summarizer():
    """compact_instructions text is appended to the summarizer system prompt."""
    provider = _make_provider("Summary with focus on k8s.")
    config = CompactConfig(max_context_tokens=100, keep_recent=2)

    compactor = AutoCompactor(
        provider, config,
        compact_instructions="Focus on Kubernetes operations and error codes.",
    )

    messages = [
        _msg("system", "sys"),
        _msg("user", "x" * 200),
        _msg("assistant", "y" * 200),
        _msg("user", "recent1"),
        _msg("assistant", "recent2"),
    ]
    await compactor.compact(messages, force_level=CompactionLevel.SUMMARIZE_OLD)

    # Check that provider.chat was called and the system prompt contains our instructions
    assert provider.chat.called
    call_messages = provider.chat.call_args[1]["messages"]
    system_prompt = call_messages[0].content
    assert "Focus on Kubernetes operations" in system_prompt
    assert "Additional instructions:" in system_prompt


async def test_compact_instructions_none_by_default():
    """Without compact_instructions, summarizer prompt has no 'Additional instructions'."""
    provider = _make_provider("Normal summary.")
    config = CompactConfig(max_context_tokens=100, keep_recent=2)

    compactor = AutoCompactor(provider, config)

    messages = [
        _msg("system", "sys"),
        _msg("user", "x" * 200),
        _msg("assistant", "y" * 200),
        _msg("user", "recent1"),
        _msg("assistant", "recent2"),
    ]
    await compactor.compact(messages, force_level=CompactionLevel.SUMMARIZE_OLD)

    assert provider.chat.called
    call_messages = provider.chat.call_args[1]["messages"]
    system_prompt = call_messages[0].content
    assert "Additional instructions:" not in system_prompt


async def test_compact_instructions_used_in_aggressive_compact():
    """compact_instructions also applies during aggressive (level 4) compaction."""
    provider = _make_provider("Aggressive summary.")
    config = CompactConfig(max_context_tokens=100, keep_recent=2)

    compactor = AutoCompactor(
        provider, config,
        compact_instructions="Prioritize security-related actions.",
    )

    messages = [
        _msg("system", "sys"),
        _msg("user", "a" * 200),
        _msg("assistant", "b" * 200),
        _msg("user", "c" * 200),
        _msg("assistant", "d" * 200),
        _msg("user", "e" * 200),
        _msg("assistant", "f" * 200),
    ]
    await compactor.compact(messages, force_level=CompactionLevel.AGGRESSIVE_COMPACT)

    # Provider.chat may be called multiple times (level 3 + level 4)
    # At least one call should have our instructions
    found = False
    for c in provider.chat.call_args_list:
        msgs = c[1]["messages"]
        if any("Prioritize security-related" in (m.content or "") for m in msgs):
            found = True
            break
    assert found, "compact_instructions should appear in at least one summarizer call"


async def test_both_hooks_and_instructions_together():
    """POST_COMPACT hook and compact_instructions work together."""
    provider = _make_provider("Combined summary.")
    hook_calls = []

    async def on_post(messages, level):
        hook_calls.append(level)

    config = CompactConfig(max_context_tokens=100, keep_recent=2)
    compactor = AutoCompactor(
        provider, config,
        on_post_compact=on_post,
        compact_instructions="Keep error messages verbatim.",
    )

    messages = [
        _msg("system", "sys"),
        _msg("user", "x" * 200),
        _msg("assistant", "y" * 200),
        _msg("user", "recent"),
        _msg("assistant", "ok"),
    ]
    result = await compactor.compact(messages, force_level=CompactionLevel.SUMMARIZE_OLD)

    # Hook fired
    assert len(hook_calls) == 1
    # Instructions were used
    call_messages = provider.chat.call_args[1]["messages"]
    assert "Keep error messages verbatim" in call_messages[0].content
    # Result is valid
    assert isinstance(result, list)
