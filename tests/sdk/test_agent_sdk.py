import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.sdk.agent import Agent, AgentConfig, PromptConfig, SafetyConfig, MemoryConfig
from breadmind.core.protocols import LLMResponse, TokenUsage


@pytest.fixture
def mock_provider():
    p = AsyncMock()
    p.chat = AsyncMock(return_value=LLMResponse(
        content="Hello from SDK!", tool_calls=[],
        usage=TokenUsage(10, 5), stop_reason="end_turn",
    ))
    p.supports_feature.return_value = False
    p.fallback = None
    return p


def test_agent_creation_minimal():
    agent = Agent(name="TestBot")
    assert agent.name == "TestBot"
    assert agent.config.max_turns == 10


def test_agent_creation_full():
    agent = Agent(
        name="FullBot",
        config=AgentConfig(provider="claude", model="claude-sonnet-4-6", max_turns=15),
        prompt=PromptConfig(persona="friendly", language="en"),
        safety=SafetyConfig(autonomy="auto"),
        memory=MemoryConfig(working=True, episodic=True),
    )
    assert agent.config.max_turns == 15
    assert agent.prompt.language == "en"
    assert agent.safety_config.autonomy == "auto"


@pytest.mark.asyncio
async def test_agent_run(mock_provider):
    agent = Agent(name="TestBot", plugins={"provider": mock_provider})
    result = await agent.run("hello")
    assert result == "Hello from SDK!"
    mock_provider.chat.assert_called_once()


@pytest.mark.asyncio
async def test_agent_run_no_provider():
    agent = Agent(name="TestBot")
    with pytest.raises(ValueError, match="Provider not configured"):
        await agent.run("hello")


def test_agent_build_safety():
    agent = Agent(
        name="Safe",
        safety=SafetyConfig(autonomy="confirm-all", blocked_patterns=["rm -rf"]),
    )
    agent._build()
    assert agent._safety._autonomy == "confirm-all"


def test_agent_build_working_memory():
    agent = Agent(name="Mem", memory=MemoryConfig(working=True, max_messages=20))
    agent._build()
    assert agent._working_memory is not None
    assert agent._working_memory._max_messages == 20


def test_agent_build_no_memory():
    agent = Agent(name="NoMem", memory=MemoryConfig(working=False))
    agent._build()
    assert agent._working_memory is None
