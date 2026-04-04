"""Spawner ↔ MessageLoopAgent 연동 통합 테스트."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.core.protocols import (
    AgentContext, AgentResponse, LLMResponse, PromptBlock, PromptContext,
    TokenUsage,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.agent_loop.spawner import Spawner
from breadmind.plugins.builtin.safety.guard import SafetyVerdict
from breadmind.plugins.builtin.tools.spawn_tool import (
    SpawnToolExecutor, SPAWN_TOOL_DEFINITION, SEND_MESSAGE_TOOL_DEFINITION,
)


# ── fixtures ──────────────────────────────────────────────────────────


def _make_provider(response_text: str = "Done") -> AsyncMock:
    provider = AsyncMock()
    provider.supports_feature.return_value = False
    provider.chat.return_value = LLMResponse(
        content=response_text, tool_calls=[],
        usage=TokenUsage(10, 5), stop_reason="end_turn",
    )
    return provider


def _make_prompt_builder() -> MagicMock:
    builder = MagicMock()
    builder.build.return_value = [
        PromptBlock(section="system", content="You are a helper.", cacheable=False, priority=0),
    ]
    return builder


def _make_tool_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_schemas.return_value = []
    return registry


def _make_safety() -> MagicMock:
    guard = MagicMock()
    guard.check.return_value = SafetyVerdict(allowed=True)
    return guard


def _spawner_factory(provider, prompt_builder, tool_registry, safety_guard):
    """테스트용 spawner_factory: 경량 Spawner 생성."""
    return Spawner(agent_factory=None, max_depth=3)


def _make_agent(*, spawner_factory=None, response_text="Done") -> MessageLoopAgent:
    return MessageLoopAgent(
        provider=_make_provider(response_text),
        prompt_builder=_make_prompt_builder(),
        tool_registry=_make_tool_registry(),
        safety_guard=_make_safety(),
        max_turns=5,
        spawner_factory=spawner_factory,
    )


# ── spawner_factory=None → NotImplementedError ──────────────────────


@pytest.mark.asyncio
async def test_spawn_without_factory_raises():
    agent = _make_agent(spawner_factory=None)
    with pytest.raises(NotImplementedError, match="Spawner plugin required"):
        await agent.spawn("do something")


@pytest.mark.asyncio
async def test_send_message_without_spawner_raises():
    agent = _make_agent(spawner_factory=None)
    with pytest.raises(NotImplementedError, match="No spawner initialized"):
        await agent.send_message("agent_abc", "hello")


# ── spawn() 성공 → child agent 생성 ─────────────────────────────────


@pytest.mark.asyncio
async def test_spawn_creates_child():
    agent = _make_agent(spawner_factory=_spawner_factory)
    child = await agent.spawn("analyze logs")

    assert child.agent_id.startswith("agent_")
    assert child.agent_id != agent.agent_id
    # spawner가 child를 추적하는지 확인
    assert child.agent_id in agent._spawner._children


# ── send_message()로 child에 메시지 전달 ─────────────────────────────


@pytest.mark.asyncio
async def test_send_message_to_child():
    agent = _make_agent(spawner_factory=_spawner_factory)
    child = await agent.spawn("initial task")

    result = await agent.send_message(child.agent_id, "follow up question")
    # child의 provider.chat이 호출되어 응답이 반환됨
    assert isinstance(result, str)
    assert len(result) > 0


# ── 존재하지 않는 target → KeyError ─────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_unknown_target_raises():
    agent = _make_agent(spawner_factory=_spawner_factory)
    # spawn을 한 번 호출하여 spawner를 초기화
    await agent.spawn("init")

    with pytest.raises(KeyError, match="No child agent with id"):
        await agent.send_message("nonexistent_agent", "hello")


# ── SpawnToolExecutor를 통한 LLM-driven spawn ───────────────────────


@pytest.mark.asyncio
async def test_spawn_tool_executor():
    agent = _make_agent(spawner_factory=_spawner_factory, response_text="Task completed")
    executor = SpawnToolExecutor(agent)

    result = await executor.execute_spawn("deploy the app", role="k8s_expert")
    assert "[Agent " in result
    assert "agent_" in result


@pytest.mark.asyncio
async def test_spawn_tool_executor_send():
    agent = _make_agent(spawner_factory=_spawner_factory, response_text="OK")
    # spawn a child first
    child = await agent.spawn("setup")
    executor = SpawnToolExecutor(agent)

    result = await executor.execute_send(child.agent_id, "status?")
    assert isinstance(result, str)


# ── depth limit 초과 시 spawn 거부 ───────────────────────────────────


@pytest.mark.asyncio
async def test_depth_limit_on_spawner():
    """Spawner.spawn()의 depth limit이 spawn_child에는 직접 적용되지 않지만,
    Spawner.spawn() (SwarmPlan 용)에서는 depth 제한이 적용되는지 확인."""
    spawner = Spawner(agent_factory=None, max_depth=2)
    ctx = AgentContext(user="test", channel="cli", session_id="s1", depth=2)
    result = await spawner.spawn("deep task", ctx)
    assert result.success is False
    assert "depth" in result.response.lower()


# ── tool definitions 검증 ────────────────────────────────────────────


def test_spawn_tool_definition():
    assert SPAWN_TOOL_DEFINITION.name == "spawn_agent"
    assert SPAWN_TOOL_DEFINITION.readonly is False
    props = SPAWN_TOOL_DEFINITION.parameters["properties"]
    assert "prompt" in props
    assert "role" in props


def test_send_message_tool_definition():
    assert SEND_MESSAGE_TOOL_DEFINITION.name == "send_message"
    assert SEND_MESSAGE_TOOL_DEFINITION.readonly is False
    props = SEND_MESSAGE_TOOL_DEFINITION.parameters["properties"]
    assert "target" in props
    assert "message" in props


# ── 여러 child spawn 후 개별 메시지 전달 ─────────────────────────────


@pytest.mark.asyncio
async def test_multiple_children():
    agent = _make_agent(spawner_factory=_spawner_factory)
    child1 = await agent.spawn("task A")
    child2 = await agent.spawn("task B")

    assert child1.agent_id != child2.agent_id
    assert len(agent._spawner._children) == 2

    # 각각에 메시지 전달 가능
    r1 = await agent.send_message(child1.agent_id, "update A")
    r2 = await agent.send_message(child2.agent_id, "update B")
    assert isinstance(r1, str)
    assert isinstance(r2, str)
