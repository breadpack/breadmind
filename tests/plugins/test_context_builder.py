import pytest
from unittest.mock import AsyncMock
from breadmind.core.protocols import Episode, KGTriple, PromptBlock
from breadmind.plugins.v2_builtin.memory.smart_retriever import SmartRetriever
from breadmind.plugins.v2_builtin.memory.context_builder import ContextBuilder


@pytest.fixture
def episodic():
    ep = AsyncMock()
    ep.episodic_search = AsyncMock(return_value=[
        Episode(id="e1", content="K8s pod crashed yesterday", keywords=["k8s", "crash"]),
    ])
    return ep


@pytest.fixture
def semantic():
    sem = AsyncMock()
    sem.semantic_query = AsyncMock(return_value=[
        KGTriple(subject="pod-nginx", predicate="runs_on", object="node-1"),
    ])
    return sem


@pytest.mark.asyncio
async def test_retriever_combines_sources(episodic, semantic):
    retriever = SmartRetriever(episodic=episodic, semantic=semantic)
    results = await retriever.retrieve("K8s pod-nginx crash")
    assert len(results) >= 1
    assert any("Episode" in r for r in results)


@pytest.mark.asyncio
async def test_retriever_episodic_only(episodic):
    retriever = SmartRetriever(episodic=episodic)
    results = await retriever.retrieve("K8s crash")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_retriever_empty():
    retriever = SmartRetriever()
    results = await retriever.retrieve("anything")
    assert results == []


@pytest.mark.asyncio
async def test_context_builder_returns_prompt_block(episodic, semantic):
    retriever = SmartRetriever(episodic=episodic, semantic=semantic)
    builder = ContextBuilder(retriever=retriever)
    block = await builder.build_context_block("s1", "K8s pod crash", budget_tokens=500)
    assert isinstance(block, PromptBlock)
    assert block.section == "memory_context"
    assert "Relevant context" in block.content
    assert block.cacheable is False


@pytest.mark.asyncio
async def test_context_builder_empty_memory():
    retriever = SmartRetriever()
    builder = ContextBuilder(retriever=retriever)
    block = await builder.build_context_block("s1", "anything", budget_tokens=500)
    assert block.content == ""


@pytest.mark.asyncio
async def test_context_builder_respects_budget(episodic):
    episodic.episodic_search = AsyncMock(return_value=[
        Episode(id=f"e{i}", content="x" * 200, keywords=["test"]) for i in range(10)
    ])
    retriever = SmartRetriever(episodic=episodic)
    builder = ContextBuilder(retriever=retriever)
    block = await builder.build_context_block("s1", "test", budget_tokens=100)
    # Should not include all 10 episodes due to budget
    assert len(block.content) < 2500
