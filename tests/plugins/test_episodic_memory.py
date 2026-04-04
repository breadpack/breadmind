import pytest
from breadmind.core.protocols import Episode, KGTriple
from breadmind.plugins.v2_builtin.memory.episodic_memory import EpisodicMemory
from breadmind.plugins.v2_builtin.memory.semantic_memory import SemanticMemory


# --- Episodic ---

@pytest.mark.asyncio
async def test_save_and_search():
    mem = EpisodicMemory()
    await mem.episodic_save(Episode(id="e1", content="K8s pod crashed", keywords=["k8s", "pod", "crash"]))
    await mem.episodic_save(Episode(id="e2", content="Proxmox VM migrated", keywords=["proxmox", "vm"]))
    results = await mem.episodic_search("pod crash", limit=5)
    assert len(results) >= 1
    assert results[0].id == "e1"


@pytest.mark.asyncio
async def test_search_wildcard():
    mem = EpisodicMemory()
    await mem.episodic_save(Episode(id="e1", content="A", keywords=[]))
    await mem.episodic_save(Episode(id="e2", content="B", keywords=[]))
    results = await mem.episodic_search("*", limit=10)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_no_match():
    mem = EpisodicMemory()
    await mem.episodic_save(Episode(id="e1", content="K8s pods", keywords=["k8s"]))
    results = await mem.episodic_search("totally unrelated xyz")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_max_episodes():
    mem = EpisodicMemory(max_episodes=3)
    for i in range(5):
        await mem.episodic_save(Episode(id=f"e{i}", content=f"ep-{i}", keywords=[]))
    assert mem.count() == 3


# --- Semantic ---

@pytest.mark.asyncio
async def test_upsert_and_query():
    mem = SemanticMemory()
    await mem.semantic_upsert([
        KGTriple(subject="pod-nginx", predicate="runs_on", object="node-1"),
        KGTriple(subject="pod-redis", predicate="runs_on", object="node-2"),
    ])
    results = await mem.semantic_query(["pod-nginx"])
    assert len(results) == 1
    assert results[0].object == "node-1"


@pytest.mark.asyncio
async def test_upsert_replaces():
    mem = SemanticMemory()
    await mem.semantic_upsert([KGTriple(subject="pod-nginx", predicate="runs_on", object="node-1")])
    await mem.semantic_upsert([KGTriple(subject="pod-nginx", predicate="runs_on", object="node-3")])
    results = await mem.semantic_query(["pod-nginx"])
    assert len(results) == 1
    assert results[0].object == "node-3"
    assert mem.count() == 1


@pytest.mark.asyncio
async def test_query_by_object():
    mem = SemanticMemory()
    await mem.semantic_upsert([
        KGTriple(subject="pod-a", predicate="runs_on", object="node-1"),
        KGTriple(subject="pod-b", predicate="runs_on", object="node-1"),
    ])
    results = await mem.semantic_query(["node-1"])
    assert len(results) == 2
