import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from breadmind.memory.working import WorkingMemory, ConversationSession
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory
from breadmind.memory.profiler import UserProfiler, UserPreference, UserPattern
from breadmind.memory.context_builder import ContextBuilder
from breadmind.storage.models import EpisodicNote, KGEntity, KGRelation
from breadmind.llm.base import LLMMessage


# =========================================================================
# Working Memory
# =========================================================================

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


# =========================================================================
# Episodic Memory (in-memory)
# =========================================================================

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

@pytest.mark.asyncio
async def test_episodic_backward_compat_no_db():
    """Without DB, episodic memory should work purely in-memory."""
    em = EpisodicMemory()  # no db argument
    note = await em.add_note("test", keywords=["kw"], tags=["tag"], context_description="ctx")
    assert note.id is not None
    results = await em.search_by_keywords(["kw"])
    assert len(results) == 1
    results = await em.search_by_tags(["tag"])
    assert len(results) == 1
    all_notes = await em.get_all_notes()
    assert len(all_notes) == 1


# =========================================================================
# Episodic Memory - Forgetting Curve
# =========================================================================

@pytest.mark.asyncio
async def test_forgetting_curve_decay():
    em = EpisodicMemory()
    note = await em.add_note("Old note", keywords=["test"], tags=[], context_description="")
    # Simulate note created 10 days ago
    note.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    em.apply_decay()
    expected = 0.95 ** 10
    assert abs(note.decay_weight - expected) < 0.001

@pytest.mark.asyncio
async def test_forgetting_curve_recent_note():
    em = EpisodicMemory()
    note = await em.add_note("Recent", keywords=["test"], tags=[], context_description="")
    # Just created, decay should be near 1.0
    em.apply_decay()
    assert note.decay_weight > 0.99

@pytest.mark.asyncio
async def test_cleanup_low_relevance():
    em = EpisodicMemory()
    n1 = await em.add_note("Old", keywords=["a"], tags=[], context_description="")
    n2 = await em.add_note("Recent", keywords=["b"], tags=[], context_description="")
    # Set one below threshold
    n1.decay_weight = 0.05
    n2.decay_weight = 0.8
    removed = await em.cleanup_low_relevance(threshold=0.1)
    assert removed == 1
    remaining = await em.get_all_notes()
    assert len(remaining) == 1
    assert remaining[0].content == "Recent"

@pytest.mark.asyncio
async def test_search_factors_decay_weight():
    em = EpisodicMemory()
    n1 = await em.add_note("Topic A old", keywords=["topic"], tags=[], context_description="")
    n2 = await em.add_note("Topic A new", keywords=["topic"], tags=[], context_description="")
    n1.decay_weight = 0.3
    n2.decay_weight = 1.0
    results = await em.search_by_keywords(["topic"], limit=2)
    # Higher decay_weight should rank first
    assert results[0].content == "Topic A new"


# =========================================================================
# Episodic Memory - DB Persistence (mocked)
# =========================================================================

def _make_mock_db():
    db = MagicMock()
    db.save_note = AsyncMock(return_value=42)
    db.search_notes_by_keywords = AsyncMock(return_value=[
        EpisodicNote(id=1, content="DB note", keywords=["k8s"], tags=[], context_description="")
    ])
    db.search_notes_by_tags = AsyncMock(return_value=[
        EpisodicNote(id=1, content="DB note", keywords=[], tags=["k8s"], context_description="")
    ])
    db.delete_note = AsyncMock(return_value=True)
    db.link_notes = AsyncMock()
    db.get_all_notes = AsyncMock(return_value=[])
    db.delete_notes_below_weight = AsyncMock(return_value=2)
    return db


@pytest.mark.asyncio
async def test_episodic_db_save():
    db = _make_mock_db()
    em = EpisodicMemory(db=db)
    note = await em.add_note("DB test", keywords=["test"], tags=["t"], context_description="ctx")
    db.save_note.assert_awaited_once()
    assert note.id == 42

@pytest.mark.asyncio
async def test_episodic_db_search_keywords():
    db = _make_mock_db()
    em = EpisodicMemory(db=db)
    results = await em.search_by_keywords(["k8s"])
    db.search_notes_by_keywords.assert_awaited_once_with(["k8s"], 5)
    assert len(results) == 1
    assert results[0].content == "DB note"

@pytest.mark.asyncio
async def test_episodic_db_search_tags():
    db = _make_mock_db()
    em = EpisodicMemory(db=db)
    results = await em.search_by_tags(["k8s"])
    db.search_notes_by_tags.assert_awaited_once_with(["k8s"], 5)
    assert len(results) == 1

@pytest.mark.asyncio
async def test_episodic_db_delete():
    db = _make_mock_db()
    em = EpisodicMemory(db=db)
    # Add a note to in-memory list so delete returns True
    note = await em.add_note("x", keywords=[], tags=[], context_description="")
    result = await em.delete_note(note.id)
    db.delete_note.assert_awaited_once()
    assert result is True

@pytest.mark.asyncio
async def test_episodic_db_link():
    db = _make_mock_db()
    em = EpisodicMemory(db=db)
    n1 = await em.add_note("A", keywords=[], tags=[], context_description="")
    n2 = await em.add_note("B", keywords=[], tags=[], context_description="")
    await em.link_notes(n1.id, n2.id)
    db.link_notes.assert_awaited_once()


# =========================================================================
# Semantic Memory (in-memory)
# =========================================================================

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

@pytest.mark.asyncio
async def test_semantic_backward_compat_no_db():
    sm = SemanticMemory()  # no db
    await sm.add_entity(KGEntity(id="x", entity_type="t", name="n"))
    e = await sm.get_entity("x")
    assert e is not None


# =========================================================================
# Semantic Memory - DB Persistence (mocked)
# =========================================================================

def _make_mock_kg_db():
    db = MagicMock()
    db.save_entity = AsyncMock()
    db.save_relation = AsyncMock(return_value=1)
    db.get_entity = AsyncMock(return_value=KGEntity(id="e1", entity_type="infra", name="pod-x"))
    db.get_neighbors = AsyncMock(return_value=[
        KGEntity(id="e2", entity_type="infra", name="svc-x")
    ])
    db.search_entities = AsyncMock(return_value=[
        KGEntity(id="e1", entity_type="infra", name="pod-x")
    ])
    return db


@pytest.mark.asyncio
async def test_semantic_db_save_entity():
    db = _make_mock_kg_db()
    sm = SemanticMemory(db=db)
    entity = KGEntity(id="e1", entity_type="infra", name="pod-x")
    await sm.add_entity(entity)
    db.save_entity.assert_awaited_once()

@pytest.mark.asyncio
async def test_semantic_db_save_relation():
    db = _make_mock_kg_db()
    sm = SemanticMemory(db=db)
    rel = KGRelation(source_id="e1", target_id="e2", relation_type="depends_on")
    await sm.add_relation(rel)
    db.save_relation.assert_awaited_once()

@pytest.mark.asyncio
async def test_semantic_db_get_neighbors():
    db = _make_mock_kg_db()
    sm = SemanticMemory(db=db)
    neighbors = await sm.get_neighbors("e1")
    db.get_neighbors.assert_awaited_once_with("e1")
    assert len(neighbors) == 1

@pytest.mark.asyncio
async def test_semantic_db_get_entity():
    db = _make_mock_kg_db()
    sm = SemanticMemory(db=db)
    e = await sm.get_entity("e1")
    db.get_entity.assert_awaited_once_with("e1")
    assert e.name == "pod-x"


# =========================================================================
# Profiler
# =========================================================================

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


# =========================================================================
# Context Builder
# =========================================================================

@pytest.mark.asyncio
async def test_context_builder_builds_correct_messages():
    wm = WorkingMemory()
    wm.get_or_create_session("s1", user="user1", channel="cli")
    wm.add_message("s1", LLMMessage(role="user", content="check pod-nginx status"))
    wm.add_message("s1", LLMMessage(role="assistant", content="pod is running"))

    em = EpisodicMemory()
    await em.add_note(
        "Previously checked pod-nginx and it was crashing",
        keywords=["pod-nginx", "check", "status"],
        tags=["k8s"],
        context_description="K8s troubleshooting",
    )

    sm = SemanticMemory()
    await sm.add_entity(KGEntity(
        id="e1", entity_type="infra", name="pod-nginx",
        properties={"namespace": "default"},
    ))

    profiler = UserProfiler()
    await profiler.add_preference("user1", UserPreference(
        category="snapshot", description="Always snapshot before changes",
    ))

    cb = ContextBuilder(wm, em, sm, profiler)
    messages = await cb.build_context("s1", "check pod-nginx status")

    # Should contain: user profile, episodic, semantic, then conversation history
    assert len(messages) >= 4
    roles = [m.role for m in messages]
    assert roles.count("system") >= 3  # profile + episodic + semantic
    # Last messages should be conversation history
    assert messages[-2].role == "user"
    assert messages[-1].role == "assistant"

@pytest.mark.asyncio
async def test_context_builder_no_optional_layers():
    wm = WorkingMemory()
    wm.get_or_create_session("s1", user="user1")
    wm.add_message("s1", LLMMessage(role="user", content="hello"))

    cb = ContextBuilder(wm)
    messages = await cb.build_context("s1", "hello")
    assert len(messages) == 1
    assert messages[0].role == "user"

@pytest.mark.asyncio
async def test_context_builder_keyword_extraction():
    wm = WorkingMemory()
    cb = ContextBuilder(wm)
    keywords = cb._extract_keywords("Check the pod-nginx status in kubernetes")
    assert "pod-nginx" in keywords
    assert "status" in keywords
    assert "kubernetes" in keywords
    # Stopwords should be removed
    assert "the" not in keywords
    assert "in" not in keywords

@pytest.mark.asyncio
async def test_context_builder_keyword_extraction_dedup():
    wm = WorkingMemory()
    cb = ContextBuilder(wm)
    keywords = cb._extract_keywords("pod pod pod nginx nginx")
    assert keywords.count("pod") == 1
    assert keywords.count("nginx") == 1


# =========================================================================
# Memory Promotion
# =========================================================================

@pytest.mark.asyncio
async def test_promote_to_episodic_creates_note():
    wm = WorkingMemory()
    em = EpisodicMemory()
    wm.get_or_create_session("s1", user="user1")

    # Add enough messages to exceed threshold
    for i in range(12):
        wm.add_message("s1", LLMMessage(role="user", content=f"message about kubernetes pod {i}"))
        wm.add_message("s1", LLMMessage(role="assistant", content=f"response {i}"))

    cb = ContextBuilder(wm, episodic_memory=em)
    note = await cb.promote_to_episodic("s1", message_threshold=10)

    assert note is not None
    assert note.content.startswith("Session summary:")
    assert "auto-promoted" in note.tags
    assert len(note.keywords) > 0

@pytest.mark.asyncio
async def test_promote_to_episodic_below_threshold():
    wm = WorkingMemory()
    em = EpisodicMemory()
    wm.get_or_create_session("s1")
    wm.add_message("s1", LLMMessage(role="user", content="short session"))

    cb = ContextBuilder(wm, episodic_memory=em)
    note = await cb.promote_to_episodic("s1", message_threshold=10)
    assert note is None

@pytest.mark.asyncio
async def test_promote_to_episodic_no_episodic():
    wm = WorkingMemory()
    cb = ContextBuilder(wm)
    note = await cb.promote_to_episodic("s1")
    assert note is None

@pytest.mark.asyncio
async def test_promote_to_semantic_creates_entities():
    em = EpisodicMemory()
    sm = SemanticMemory()
    wm = WorkingMemory()

    await em.add_note(
        "Checked pod-nginx on 192.168.1.100 at server.example.com",
        keywords=["pod-nginx", "check"],
        tags=["k8s"],
        context_description="K8s troubleshooting",
    )

    cb = ContextBuilder(wm, episodic_memory=em, semantic_memory=sm)
    entities = await cb.promote_to_semantic()

    assert len(entities) >= 2  # At least IP + hostname
    entity_names = [e.name for e in entities]
    assert "192.168.1.100" in entity_names
    assert "server.example.com" in entity_names

@pytest.mark.asyncio
async def test_promote_to_semantic_infra_names():
    em = EpisodicMemory()
    sm = SemanticMemory()
    wm = WorkingMemory()

    await em.add_note(
        "Deploy svc-frontend depends on pod-backend",
        keywords=["deploy"],
        tags=[],
        context_description="",
    )

    cb = ContextBuilder(wm, episodic_memory=em, semantic_memory=sm)
    entities = await cb.promote_to_semantic()

    entity_names = [e.name.lower() for e in entities]
    assert any("svc-frontend" in n for n in entity_names)
    assert any("pod-backend" in n for n in entity_names)

@pytest.mark.asyncio
async def test_promote_to_semantic_no_semantic():
    wm = WorkingMemory()
    cb = ContextBuilder(wm)
    entities = await cb.promote_to_semantic()
    assert entities == []
