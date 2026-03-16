import pytest
from unittest.mock import AsyncMock
from breadmind.core.reflexion import ReflexionEngine
from breadmind.llm.base import LLMResponse, TokenUsage
from breadmind.storage.models import EpisodicNote


@pytest.fixture
def engine():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="Always check pod status before scaling.",
        tool_calls=[], usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="end_turn",
    ))
    episodic = AsyncMock()
    episodic.add_note = AsyncMock(return_value=EpisodicNote(
        content="test", keywords=[], tags=[], context_description="", id=1,
    ))
    episodic.search_by_tags = AsyncMock(return_value=[])
    return ReflexionEngine(provider, episodic)


@pytest.mark.asyncio
async def test_reflect_on_failure(engine):
    lesson = await engine.reflect_on_failure(
        "Scale deployment nginx to 5 replicas",
        "Pod quota exceeded",
    )
    assert lesson is not None
    assert len(lesson) > 10
    engine._episodic.add_note.assert_called_once()


@pytest.mark.asyncio
async def test_store_success(engine):
    await engine.store_success("Deploy nginx", "Successfully deployed 3 replicas")
    engine._episodic.add_note.assert_called_once()
    call_kwargs = engine._episodic.add_note.call_args
    assert "success_trajectory" in call_kwargs.kwargs["tags"]
