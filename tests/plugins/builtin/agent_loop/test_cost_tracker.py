"""CostTracker 단위 테스트."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.plugins.builtin.agent_loop.cost_tracker import (
    CostTracker,
    UsageSnapshot,
)
from breadmind.core.protocols import (
    AgentContext,
    LLMResponse,
    Message,
    PromptBlock,
    TokenUsage,
    ToolCallRequest,
    ToolResult,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.guard import SafetyVerdict


# ── CostTracker 단위 테스트 ──


class TestCostTrackerRecord:
    """record() 비용 계산 정확성."""

    def test_sonnet_cost(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        cost = tracker.record(1_000_000, 1_000_000)
        # input: 3.0 + output: 15.0 = 18.0
        assert cost == pytest.approx(18.0)

    def test_haiku_cost(self):
        tracker = CostTracker(model="claude-haiku-4-5")
        cost = tracker.record(1_000_000, 1_000_000)
        # input: 0.80 + output: 4.0 = 4.80
        assert cost == pytest.approx(4.80)

    def test_opus_cost(self):
        tracker = CostTracker(model="claude-opus-4-6")
        cost = tracker.record(1_000_000, 1_000_000)
        # input: 15.0 + output: 75.0 = 90.0
        assert cost == pytest.approx(90.0)

    def test_gemini_flash_cost(self):
        tracker = CostTracker(model="gemini-2.5-flash")
        cost = tracker.record(1_000_000, 1_000_000)
        # input: 0.15 + output: 0.60 = 0.75
        assert cost == pytest.approx(0.75)

    def test_gemini_pro_cost(self):
        tracker = CostTracker(model="gemini-2.5-pro")
        cost = tracker.record(1_000_000, 1_000_000)
        # input: 1.25 + output: 10.0 = 11.25
        assert cost == pytest.approx(11.25)

    def test_grok3_cost(self):
        tracker = CostTracker(model="grok-3")
        cost = tracker.record(1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_grok3_mini_cost(self):
        tracker = CostTracker(model="grok-3-mini")
        cost = tracker.record(1_000_000, 1_000_000)
        # input: 0.30 + output: 0.50 = 0.80
        assert cost == pytest.approx(0.80)

    def test_model_override(self):
        """record()에 model 인자로 다른 모델 가격 적용."""
        tracker = CostTracker(model="claude-sonnet-4-6")
        cost = tracker.record(1_000_000, 1_000_000, model="claude-haiku-4-5")
        assert cost == pytest.approx(4.80)


class TestCostTrackerUnknownModel:
    """알 수 없는 모델은 비용 $0."""

    def test_unknown_model_zero_cost(self):
        tracker = CostTracker(model="unknown-model-xyz")
        cost = tracker.record(1_000_000, 1_000_000)
        assert cost == 0.0

    def test_unknown_override_zero_cost(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        cost = tracker.record(1_000_000, 1_000_000, model="nonexistent")
        assert cost == 0.0


class TestCostTrackerCacheTokens:
    """cache token 포함 비용 계산."""

    def test_cache_creation_cost(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        cost = tracker.record(0, 0, cache_creation=1_000_000)
        # cache_creation: 3.75
        assert cost == pytest.approx(3.75)

    def test_cache_read_cost(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        cost = tracker.record(0, 0, cache_read=1_000_000)
        # cache_read: 0.30
        assert cost == pytest.approx(0.30)

    def test_full_cache_scenario(self):
        tracker = CostTracker(model="claude-opus-4-6")
        cost = tracker.record(
            500_000, 100_000,
            cache_creation=200_000, cache_read=300_000,
        )
        expected = (
            500_000 * 15.0 / 1_000_000
            + 100_000 * 75.0 / 1_000_000
            + 200_000 * 18.75 / 1_000_000
            + 300_000 * 1.50 / 1_000_000
        )
        assert cost == pytest.approx(expected)


class TestCostTrackerSnapshot:
    """snapshot() 누적 확인."""

    def test_cumulative_snapshot(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        tracker.record(100, 50)
        tracker.record(200, 100, cache_creation=10, cache_read=20)

        snap = tracker.snapshot()
        assert snap.input_tokens == 300
        assert snap.output_tokens == 150
        assert snap.cache_creation_tokens == 10
        assert snap.cache_read_tokens == 20
        assert snap.api_calls == 2
        assert snap.cost_usd > 0

    def test_empty_snapshot(self):
        tracker = CostTracker()
        snap = tracker.snapshot()
        assert snap == UsageSnapshot()


class TestCostTrackerProperties:
    """total_cost, total_tokens, api_calls 프로퍼티."""

    def test_total_tokens(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        tracker.record(100, 50)
        tracker.record(200, 100)
        assert tracker.total_tokens == 450  # 100+50+200+100

    def test_api_calls(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        tracker.record(10, 5)
        tracker.record(20, 10)
        tracker.record(30, 15)
        assert tracker.api_calls == 3

    def test_total_cost_accumulates(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        c1 = tracker.record(1_000_000, 0)
        c2 = tracker.record(0, 1_000_000)
        assert tracker.total_cost == pytest.approx(c1 + c2)


class TestFormatSummary:
    """format_summary() 출력 형식."""

    def test_small_cost_format(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        tracker.record(100, 50)
        summary = tracker.format_summary()
        assert "100 in / 50 out" in summary
        assert "(1 calls)" in summary
        assert "$0.00" in summary  # very small cost → 4 decimal places

    def test_large_cost_format(self):
        tracker = CostTracker(model="claude-opus-4-6")
        tracker.record(1_000_000, 1_000_000)
        summary = tracker.format_summary()
        assert "$90.00" in summary

    def test_comma_formatting(self):
        tracker = CostTracker(model="claude-sonnet-4-6")
        tracker.record(1_234_567, 890_123)
        summary = tracker.format_summary()
        assert "1,234,567 in / 890,123 out" in summary


# ── MessageLoopAgent 통합 테스트 ──


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.supports_feature.return_value = False
    provider.transform_system_prompt.side_effect = lambda blocks: blocks
    provider.transform_messages.side_effect = lambda msgs: msgs
    provider.fallback = None
    return provider


@pytest.fixture
def mock_prompt_builder():
    builder = MagicMock()
    builder.build.return_value = [
        PromptBlock(section="test", content="Test.", cacheable=True, priority=0),
    ]
    builder.inject_reminder.side_effect = (
        lambda k, c: Message(role="user", content=c, is_meta=True)
    )
    return builder


@pytest.fixture
def mock_tool_registry():
    registry = MagicMock()
    registry.get_schemas.return_value = []
    registry.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
    registry.execute_batch = AsyncMock(
        return_value=[ToolResult(success=True, output="done")],
    )
    return registry


@pytest.fixture
def mock_safety():
    guard = MagicMock()
    guard.check.return_value = SafetyVerdict(allowed=True)
    return guard


class TestMessageLoopAgentCostIntegration:
    """MessageLoopAgent + CostTracker 통합."""

    @pytest.mark.asyncio
    async def test_cost_in_response(
        self, mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
    ):
        """AgentResponse.cost_usd에 누적 비용이 포함된다."""
        tracker = CostTracker(model="claude-sonnet-4-6")
        agent = MessageLoopAgent(
            provider=mock_provider,
            prompt_builder=mock_prompt_builder,
            tool_registry=mock_tool_registry,
            safety_guard=mock_safety,
            cost_tracker=tracker,
        )
        mock_provider.chat.return_value = LLMResponse(
            content="Hi!",
            tool_calls=[],
            usage=TokenUsage(1000, 500),
            stop_reason="end_turn",
        )
        ctx = AgentContext(user="test", channel="cli", session_id="s1")
        resp = await agent.handle_message("hello", ctx)

        assert resp.cost_usd > 0
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert resp.cost_usd == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_cost_with_tool_calls(
        self, mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
    ):
        """도구 호출 포함 다중 turn에서 비용이 누적된다."""
        tracker = CostTracker(model="claude-sonnet-4-6")
        agent = MessageLoopAgent(
            provider=mock_provider,
            prompt_builder=mock_prompt_builder,
            tool_registry=mock_tool_registry,
            safety_guard=mock_safety,
            cost_tracker=tracker,
        )
        mock_provider.chat.side_effect = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="t1", name="test", arguments={})],
                usage=TokenUsage(1000, 500),
                stop_reason="tool_use",
            ),
            LLMResponse(
                content="Done.",
                tool_calls=[],
                usage=TokenUsage(2000, 800),
                stop_reason="end_turn",
            ),
        ]
        ctx = AgentContext(user="test", channel="cli", session_id="s1")
        resp = await agent.handle_message("do something", ctx)

        assert tracker.api_calls == 2
        assert resp.cost_usd == pytest.approx(tracker.total_cost)

    @pytest.mark.asyncio
    async def test_no_cost_tracker_backward_compat(
        self, mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
    ):
        """CostTracker=None일 때 기존 동작 유지 (cost_usd=0.0)."""
        agent = MessageLoopAgent(
            provider=mock_provider,
            prompt_builder=mock_prompt_builder,
            tool_registry=mock_tool_registry,
            safety_guard=mock_safety,
        )
        mock_provider.chat.return_value = LLMResponse(
            content="Hi!",
            tool_calls=[],
            usage=TokenUsage(100, 50),
            stop_reason="end_turn",
        )
        ctx = AgentContext(user="test", channel="cli", session_id="s1")
        resp = await agent.handle_message("hello", ctx)

        assert resp.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_cost_with_cache_tokens(
        self, mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
    ):
        """v2 TokenUsage의 cache 필드가 비용에 반영된다."""
        tracker = CostTracker(model="claude-sonnet-4-6")
        agent = MessageLoopAgent(
            provider=mock_provider,
            prompt_builder=mock_prompt_builder,
            tool_registry=mock_tool_registry,
            safety_guard=mock_safety,
            cost_tracker=tracker,
        )
        mock_provider.chat.return_value = LLMResponse(
            content="Cached!",
            tool_calls=[],
            usage=TokenUsage(
                input_tokens=500,
                output_tokens=200,
                cache_creation_input_tokens=1000,
                cache_read_input_tokens=2000,
            ),
            stop_reason="end_turn",
        )
        ctx = AgentContext(user="test", channel="cli", session_id="s1")
        resp = await agent.handle_message("hello", ctx)

        expected = (
            500 * 3.0 / 1_000_000
            + 200 * 15.0 / 1_000_000
            + 1000 * 3.75 / 1_000_000
            + 2000 * 0.30 / 1_000_000
        )
        assert resp.cost_usd == pytest.approx(expected)

    @pytest.mark.asyncio
    async def test_stream_done_includes_cost(
        self, mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
    ):
        """스트리밍 done 이벤트에 cost 정보가 포함된다."""
        tracker = CostTracker(model="claude-sonnet-4-6")
        agent = MessageLoopAgent(
            provider=mock_provider,
            prompt_builder=mock_prompt_builder,
            tool_registry=mock_tool_registry,
            safety_guard=mock_safety,
            cost_tracker=tracker,
        )
        mock_provider.chat.return_value = LLMResponse(
            content="Streamed!",
            tool_calls=[],
            usage=TokenUsage(1000, 500),
            stop_reason="end_turn",
        )
        # chat_stream not available => falls back to content
        del mock_provider.chat_stream

        ctx = AgentContext(user="test", channel="cli", session_id="s1")
        events = []
        async for event in agent.handle_message_stream("hello", ctx):
            events.append(event)

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        done_data = done_events[0].data
        assert "cost" in done_data
        assert "cost_detail" in done_data
        assert done_data["cost"].startswith("$")

    @pytest.mark.asyncio
    async def test_stream_done_no_cost_without_tracker(
        self, mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety,
    ):
        """CostTracker 없이 스트리밍 done 이벤트에 cost 미포함."""
        agent = MessageLoopAgent(
            provider=mock_provider,
            prompt_builder=mock_prompt_builder,
            tool_registry=mock_tool_registry,
            safety_guard=mock_safety,
        )
        mock_provider.chat.return_value = LLMResponse(
            content="Hi!",
            tool_calls=[],
            usage=TokenUsage(100, 50),
            stop_reason="end_turn",
        )
        del mock_provider.chat_stream

        ctx = AgentContext(user="test", channel="cli", session_id="s1")
        events = []
        async for event in agent.handle_message_stream("hello", ctx):
            events.append(event)

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        done_data = done_events[0].data
        assert "cost" not in done_data
