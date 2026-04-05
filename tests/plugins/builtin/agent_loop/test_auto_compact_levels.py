"""Multi-level AutoCompactor 단위 테스트."""
from __future__ import annotations

from unittest.mock import AsyncMock

from breadmind.core.protocols import LLMResponse, Message, TokenUsage
from breadmind.plugins.builtin.agent_loop.auto_compact import (
    AutoCompactor,
    CompactConfig,
    CompactionLevel,
)


def _msg(role: str, content: str, tool_call_id: str | None = None) -> Message:
    return Message(role=role, content=content, tool_call_id=tool_call_id)


def _make_provider(summary_text: str = "Summary of old conversation.") -> AsyncMock:
    provider = AsyncMock()
    provider.chat.return_value = LLMResponse(
        content=summary_text,
        tool_calls=[],
        usage=TokenUsage(),
        stop_reason="end_turn",
    )
    return provider


# ── determine_level ──────────────────────────────────────────────


class TestDetermineLevel:
    def test_determine_level_none_when_under_threshold(self):
        """50% 미만이면 NONE."""
        config = CompactConfig(max_context_tokens=1000, level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9})
        compactor = AutoCompactor(_make_provider(), config)
        # 400 chars -> 100 tokens, threshold_1 = 500
        messages = [_msg("user", "x" * 400)]
        assert compactor.determine_level(messages) == CompactionLevel.NONE

    def test_determine_level_1_tool_trim(self):
        """50% 초과, 65% 미만이면 TOOL_RESULT_TRIM."""
        config = CompactConfig(max_context_tokens=1000, level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9})
        compactor = AutoCompactor(_make_provider(), config)
        # 2200 chars -> 550 tokens, 50% = 500, 65% = 650
        messages = [_msg("user", "x" * 2200)]
        assert compactor.determine_level(messages) == CompactionLevel.TOOL_RESULT_TRIM

    def test_determine_level_2_snip_old(self):
        """65% 초과, 75% 미만이면 SNIP_OLD_RESULTS."""
        config = CompactConfig(max_context_tokens=1000, level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9})
        compactor = AutoCompactor(_make_provider(), config)
        # 2800 chars -> 700 tokens, 65% = 650, 75% = 750
        messages = [_msg("user", "x" * 2800)]
        assert compactor.determine_level(messages) == CompactionLevel.SNIP_OLD_RESULTS

    def test_determine_level_3_summarize(self):
        """75% 초과, 90% 미만이면 SUMMARIZE_OLD."""
        config = CompactConfig(max_context_tokens=1000, level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9})
        compactor = AutoCompactor(_make_provider(), config)
        # 3200 chars -> 800 tokens, 75% = 750, 90% = 900
        messages = [_msg("user", "x" * 3200)]
        assert compactor.determine_level(messages) == CompactionLevel.SUMMARIZE_OLD

    def test_determine_level_4_aggressive(self):
        """90% 초과이면 AGGRESSIVE_COMPACT."""
        config = CompactConfig(max_context_tokens=1000, level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9})
        compactor = AutoCompactor(_make_provider(), config)
        # 3800 chars -> 950 tokens, 90% = 900
        messages = [_msg("user", "x" * 3800)]
        assert compactor.determine_level(messages) == CompactionLevel.AGGRESSIVE_COMPACT


# ── _trim_tool_results (Level 1) ─────────────────────────────────


class TestTrimToolResults:
    def test_trim_tool_results_truncates_large(self):
        """5000자 이상의 tool result를 preview 크기로 자른다."""
        config = CompactConfig(tool_result_preview_size=500)
        compactor = AutoCompactor(_make_provider(), config)
        large_content = "A" * 6000
        messages = [_msg("tool", large_content, tool_call_id="tc1")]
        result = compactor._trim_tool_results(messages)
        assert len(result) == 1
        assert result[0].content.endswith("[...trimmed]")
        # 500 chars preview + "\n[...trimmed]"
        assert len(result[0].content) == 500 + len("\n[...trimmed]")

    def test_trim_tool_results_preserves_small(self):
        """5000자 미만의 tool result는 그대로 유지."""
        config = CompactConfig(tool_result_preview_size=500)
        compactor = AutoCompactor(_make_provider(), config)
        small_content = "B" * 3000
        messages = [_msg("tool", small_content, tool_call_id="tc1")]
        result = compactor._trim_tool_results(messages)
        assert result[0].content == small_content


# ── _snip_old_results (Level 2) ──────────────────────────────────


class TestSnipOldResults:
    def test_snip_old_results_clears_old_tool_messages(self):
        """keep_recent 이전의 tool result를 제거."""
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(_make_provider(), config)
        messages = [
            _msg("user", "q1"),
            _msg("tool", "old tool output", tool_call_id="tc1"),
            _msg("assistant", "a1"),
            _msg("user", "q2"),         # recent
            _msg("assistant", "a2"),    # recent
        ]
        result = compactor._snip_old_results(messages)
        # old tool message (index 1) should be snipped
        assert result[1].content == "[Old tool result content cleared]"
        assert result[1].role == "tool"

    def test_snip_preserves_recent(self):
        """keep_recent 내의 tool result는 유지."""
        config = CompactConfig(keep_recent=3)
        compactor = AutoCompactor(_make_provider(), config)
        messages = [
            _msg("user", "q1"),
            _msg("assistant", "a1"),
            _msg("tool", "recent tool output", tool_call_id="tc1"),  # within recent
            _msg("user", "q2"),
            _msg("assistant", "a2"),
        ]
        result = compactor._snip_old_results(messages)
        # tool message at index 2 is within the last 3, preserved
        assert result[2].content == "recent tool output"


# ── _summarize_old (Level 3) ─────────────────────────────────────


class TestSummarizeOld:
    async def test_summarize_calls_provider(self):
        """Level 3에서 provider.chat이 호출되어 요약을 생성."""
        provider = _make_provider("Summarized content.")
        config = CompactConfig(keep_recent=2)
        compactor = AutoCompactor(provider, config)
        messages = [
            _msg("system", "System prompt"),
            _msg("user", "old question"),
            _msg("assistant", "old answer"),
            _msg("user", "recent q"),
            _msg("assistant", "recent a"),
        ]
        result = await compactor._summarize_old(messages)
        provider.chat.assert_called_once()
        # [system, summary, recent_q, recent_a]
        assert len(result) == 4
        assert "[Previous conversation summary]" in result[1].content
        assert "Summarized content." in result[1].content


# ── _aggressive_compact (Level 4) ────────────────────────────────


class TestAggressiveCompact:
    async def test_aggressive_keeps_only_system_and_recent(self):
        """Level 4: system + 마지막 4개 메시지만 유지."""
        provider = _make_provider("Aggressive summary.")
        config = CompactConfig(keep_recent=6)  # keep_recent은 aggressive에서 무시, 4개만 유지
        compactor = AutoCompactor(provider, config)
        messages = [
            _msg("system", "System prompt"),
            _msg("user", "old1"),
            _msg("assistant", "old_resp1"),
            _msg("user", "old2"),
            _msg("assistant", "old_resp2"),
            _msg("user", "old3"),
            _msg("assistant", "old_resp3"),
            _msg("user", "recent1"),
            _msg("assistant", "recent_resp1"),
            _msg("user", "recent2"),
            _msg("assistant", "recent_resp2"),
        ]
        result = await compactor._aggressive_compact(messages)
        # system + summary + last 4
        assert len(result) == 6
        assert result[0].role == "system"
        assert result[0].content == "System prompt"
        assert "[Aggressively compacted summary]" in result[1].content
        assert result[-1].content == "recent_resp2"
        assert result[-2].content == "recent2"


# ── compact (통합) ───────────────────────────────────────────────


class TestCompactIntegration:
    async def test_compact_backward_compat_returns_list(self):
        """compact()는 list[Message]를 반환 (하위 호환)."""
        provider = _make_provider("Summary.")
        config = CompactConfig(
            max_context_tokens=1000,
            level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9},
            keep_recent=2,
        )
        compactor = AutoCompactor(provider, config)
        # 2200 chars -> 550 tokens -> level 1
        messages = [
            _msg("user", "x" * 2200),
        ]
        result = await compactor.compact(messages)
        assert isinstance(result, list)

    def test_should_compact_backward_compat(self):
        """should_compact()는 bool을 반환 (하위 호환)."""
        config = CompactConfig(
            max_context_tokens=1000,
            level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9},
        )
        compactor = AutoCompactor(_make_provider(), config)
        # Below all thresholds
        messages = [_msg("user", "x" * 100)]
        assert compactor.should_compact(messages) is False
        # Above level 1 threshold
        messages = [_msg("user", "x" * 2200)]
        assert compactor.should_compact(messages) is True

    async def test_levels_are_cumulative(self):
        """레벨이 높아질수록 이전 레벨의 변환도 포함."""
        provider = _make_provider("Summary.")
        config = CompactConfig(
            max_context_tokens=1000,
            level_thresholds={1: 0.5, 2: 0.65, 3: 0.75, 4: 0.9},
            keep_recent=2,
            tool_result_preview_size=100,
        )
        compactor = AutoCompactor(provider, config)
        messages = [
            _msg("system", "System"),
            _msg("user", "q1"),
            _msg("tool", "T" * 6000, tool_call_id="tc1"),  # large tool result
            _msg("assistant", "a1"),
            _msg("user", "q2"),
            _msg("assistant", "a2"),
        ]
        # Force level 2: should trim (L1) AND snip (L2)
        result = await compactor.compact(messages, force_level=CompactionLevel.SNIP_OLD_RESULTS)
        assert compactor.last_compact_level == CompactionLevel.SNIP_OLD_RESULTS

        # The old tool message should have been both trimmed and then snipped
        # Since snip replaces old tool content entirely, it dominates
        tool_msgs = [m for m in result if m.role == "tool"]
        for tm in tool_msgs:
            # Either trimmed or snipped (snip overwrites)
            assert "[Old tool result content cleared]" in tm.content or "[...trimmed]" in tm.content
