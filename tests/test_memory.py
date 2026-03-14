import pytest
from breadmind.memory.working import WorkingMemory, ConversationSession
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory, KGEntity, KGRelation
from breadmind.memory.profiler import UserProfiler, UserPreference, UserPattern
from breadmind.llm.base import LLMMessage

# Working Memory
def test_working_memory_create_session():
    wm = WorkingMemory()
    session = wm.get_or_create_session("s1", user="user1", channel="cli")
    assert session.session_id == "s1"
    assert session.user == "user1"

def test_working_memory_add_messages():
    wm = WorkingMemory(max_messages_per_session=3)
    wm.get_or_create_session("s1")
    for i in range(5):
        wm.add_message("s1", LLMMessage(role="user", content=f"msg {i}"))
    msgs = wm.get_messages("s1")
    assert len(msgs) == 3  # trimmed to max

def test_working_memory_clear():
    wm = WorkingMemory()
    wm.get_or_create_session("s1")
    wm.clear_session("s1")
    assert wm.get_messages("s1") == []

def test_working_memory_list_sessions():
    wm = WorkingMemory()
    wm.get_or_create_session("s1")
    wm.get_or_create_session("s2")
    assert len(wm.list_sessions()) == 2

# Episodic Memory
@pytest.mark.asyncio
async def test_episodic_add_and_search():
    em = EpisodicMemory()
    await em.add_note("User prefers snapshots", keywords=["snapshot", "preference"], tags=["proxmox"], context_description="VM management")
    await em.add_note("Restart pods when crashing", keywords=["restart", "pod"], tags=["k8s"], context_description="K8s troubleshooting")
    results = await em.search_by_keywords(["snapshot"])
    assert len(results) == 1
    assert "snapshot" in results[0].keywords

@pytest.mark.asyncio
async def test_episodic_search_by_tags():
    em = EpisodicMemory()
    await em.add_note("Note 1", keywords=[], tags=["k8s"], context_description="")
    await em.add_note("Note 2", keywords=[], tags=["proxmox"], context_description="")
    results = await em.search_by_tags(["k8s"])
    assert len(results) == 1

@pytest.mark.asyncio
async def test_episodic_link_notes():
    em = EpisodicMemory()
    n1 = await em.add_note("Note A", keywords=["a"], tags=[], context_description="")
    n2 = await em.add_note("Note B", keywords=["b"], tags=[], context_description="")
    await em.link_notes(n1.id, n2.id)
    assert n2.id in n1.linked_note_ids
    assert n1.id in n2.linked_note_ids

@pytest.mark.asyncio
async def test_episodic_delete():
    em = EpisodicMemory()
    note = await em.add_note("Temp", keywords=[], tags=[], context_description="")
    assert await em.delete_note(note.id) is True
    assert await em.get_note(note.id) is None

# Semantic Memory (KG)
@pytest.mark.asyncio
async def test_kg_add_entity():
    sm = SemanticMemory()
    await sm.add_entity(KGEntity(id="e1", entity_type="user_preference", name="snapshot_before_change"))
    entity = await sm.get_entity("e1")
    assert entity is not None
    assert entity.name == "snapshot_before_change"

@pytest.mark.asyncio
async def test_kg_relations():
    sm = SemanticMemory()
    await sm.add_entity(KGEntity(id="e1", entity_type="infra", name="pod-nginx"))
    await sm.add_entity(KGEntity(id="e2", entity_type="infra", name="svc-nginx"))
    await sm.add_relation(KGRelation(source_id="e1", target_id="e2", relation_type="depends_on"))
    neighbors = await sm.get_neighbors("e1")
    assert len(neighbors) == 1
    assert neighbors[0].id == "e2"

@pytest.mark.asyncio
async def test_kg_context_query():
    sm = SemanticMemory()
    await sm.add_entity(KGEntity(id="e1", entity_type="preference", name="snapshot policy", weight=2.0))
    await sm.add_entity(KGEntity(id="e2", entity_type="preference", name="logging level", weight=1.0))
    results = await sm.get_context_for_query(["snapshot"])
    assert len(results) == 1
    assert results[0].id == "e1"

# Profiler
@pytest.mark.asyncio
async def test_profiler_add_preference():
    p = UserProfiler()
    await p.add_preference("user1", UserPreference(category="snapshot", description="Always snapshot before VM changes"))
    prefs = await p.get_preferences("user1")
    assert len(prefs) == 1
    assert prefs[0].category == "snapshot"

@pytest.mark.asyncio
async def test_profiler_duplicate_preference_updates():
    p = UserProfiler()
    await p.add_preference("user1", UserPreference(category="snapshot", description="v1"))
    await p.add_preference("user1", UserPreference(category="snapshot", description="v2"))
    prefs = await p.get_preferences("user1")
    assert len(prefs) == 1
    assert prefs[0].description == "v2"

@pytest.mark.asyncio
async def test_profiler_patterns():
    p = UserProfiler()
    await p.add_pattern("user1", UserPattern(action="restart_pod"))
    await p.add_pattern("user1", UserPattern(action="restart_pod"))
    patterns = await p.get_patterns("user1")
    assert len(patterns) == 1
    assert patterns[0].frequency == 2

@pytest.mark.asyncio
async def test_profiler_user_context():
    p = UserProfiler()
    await p.add_preference("user1", UserPreference(category="notify", description="Always notify on Slack"))
    ctx = await p.get_user_context("user1")
    assert "notify" in ctx
    empty = await p.get_user_context("unknown")
    assert empty == ""
