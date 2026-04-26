import uuid
import pytest
from breadmind.storage.models import EpisodicNote


@pytest.mark.asyncio
async def test_save_and_load_with_new_fields(test_db):
    sid = uuid.uuid4()
    note = EpisodicNote(
        content="raw payload",
        keywords=["vpc", "create"],
        tags=[],
        context_description="ctx",
        kind="tool_executed",
        tool_name="aws_vpc_create",
        tool_args_digest="ab12cd34",
        outcome="success",
        session_id=sid,
        user_id="alice",
        summary="VPC ap-northeast-2 created.",
        pinned=False,
    )
    note_id = await test_db.save_note(note)
    rows = await test_db.search_notes_by_keywords(["vpc"], limit=5)
    assert any(
        r.id == note_id
        and r.kind == "tool_executed"
        and r.tool_name == "aws_vpc_create"
        and r.outcome == "success"
        and r.summary == "VPC ap-northeast-2 created."
        and r.session_id == sid
        and r.user_id == "alice"
        for r in rows
    )


@pytest.mark.asyncio
async def test_save_legacy_note_defaults(test_db):
    note = EpisodicNote(
        content="legacy", keywords=["x"], tags=[], context_description="",
    )
    nid = await test_db.save_note(note)
    rows = await test_db.search_notes_by_keywords(["x"], limit=5)
    r = next(r for r in rows if r.id == nid)
    assert r.kind == "neutral"
    assert r.outcome == "neutral"
    assert r.tool_name is None
    assert r.summary == ""


# ── P2: save_note_with_vector preserves Phase 1 recorder fields ──────


@pytest.mark.asyncio
async def test_save_note_with_vector_preserves_phase1_fields(test_db):
    """save_note_with_vector must INSERT all Phase 1 recorder fields too."""
    try:
        await test_db.setup_pgvector(384)
    except Exception as exc:
        pytest.skip(f"pgvector unavailable: {exc}")

    sid = uuid.uuid4()
    note = EpisodicNote(
        content="vec payload",
        keywords=["vec", "phase1"],
        tags=[],
        context_description="ctx-vec",
        kind="tool_executed",
        tool_name="aws_vpc_create",
        tool_args_digest="vec-digest-1",
        outcome="success",
        session_id=sid,
        user_id="bob",
        summary="VPC vec-test created.",
        pinned=True,
    )
    embedding = [0.0] * 384

    note_id = await test_db.save_note_with_vector(note, embedding)
    rows = await test_db.search_notes_by_keywords(["vec"], limit=5)

    saved = next(r for r in rows if r.id == note_id)
    assert saved.kind == "tool_executed"
    assert saved.tool_name == "aws_vpc_create"
    assert saved.tool_args_digest == "vec-digest-1"
    assert saved.outcome == "success"
    assert saved.session_id == sid
    assert saved.user_id == "bob"
    assert saved.summary == "VPC vec-test created."
    assert saved.pinned is True


@pytest.mark.asyncio
async def test_save_note_with_vector_legacy_defaults(test_db):
    """Notes without Phase 1 fields should fall back to model defaults."""
    try:
        await test_db.setup_pgvector(384)
    except Exception as exc:
        pytest.skip(f"pgvector unavailable: {exc}")

    note = EpisodicNote(
        content="vec legacy",
        keywords=["veclegacy"],
        tags=[],
        context_description="",
    )
    embedding = [0.0] * 384

    note_id = await test_db.save_note_with_vector(note, embedding)
    rows = await test_db.search_notes_by_keywords(["veclegacy"], limit=5)
    saved = next(r for r in rows if r.id == note_id)
    assert saved.kind == "neutral"
    assert saved.outcome == "neutral"
    assert saved.tool_name is None
    assert saved.summary == ""
    assert saved.pinned is False


# ── T3: org_id round-trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_note_persists_org_id(test_db, insert_org):
    """org_id is stored and reloaded intact via save_note."""
    oid = uuid.uuid4()
    await insert_org(oid)
    note = EpisodicNote(
        content="org-id test note",
        keywords=["orgidtest"],
        tags=[],
        context_description="",
        org_id=oid,
    )
    note_id = await test_db.save_note(note)
    rows = await test_db.search_notes_by_keywords(["orgidtest"], limit=5)
    saved = next(r for r in rows if r.id == note_id)
    assert saved.org_id == oid


@pytest.mark.asyncio
async def test_save_note_org_id_none_regression(test_db):
    """org_id=None (legacy) saves and reads back as None without error."""
    note = EpisodicNote(
        content="legacy no org",
        keywords=["orgnulltest"],
        tags=[],
        context_description="",
        org_id=None,
    )
    note_id = await test_db.save_note(note)
    rows = await test_db.search_notes_by_keywords(["orgnulltest"], limit=5)
    saved = next(r for r in rows if r.id == note_id)
    assert saved.org_id is None


@pytest.mark.asyncio
async def test_save_note_with_vector_persists_org_id(test_db, insert_org):
    """org_id is stored and reloaded intact via save_note_with_vector."""
    try:
        await test_db.setup_pgvector(384)
    except Exception as exc:
        pytest.skip(f"pgvector unavailable: {exc}")

    oid = uuid.uuid4()
    await insert_org(oid)
    note = EpisodicNote(
        content="org-id vec test",
        keywords=["orgidvectest"],
        tags=[],
        context_description="",
        org_id=oid,
    )
    embedding = [0.0] * 384

    note_id = await test_db.save_note_with_vector(note, embedding)
    rows = await test_db.search_notes_by_keywords(["orgidvectest"], limit=5)
    saved = next(r for r in rows if r.id == note_id)
    assert saved.org_id == oid


@pytest.mark.asyncio
async def test_search_notes_by_keywords_org_id_isolation(test_db, insert_org):
    """search_notes_by_keywords with org_id returns only that org's notes (plus NULL-org)."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    kw = "orgisokw"

    await insert_org(org_a)
    await insert_org(org_b)

    note_a = EpisodicNote(
        content="note for org A", keywords=[kw], tags=[], context_description="", org_id=org_a
    )
    note_b = EpisodicNote(
        content="note for org B", keywords=[kw], tags=[], context_description="", org_id=org_b
    )
    note_null = EpisodicNote(
        content="note no org", keywords=[kw], tags=[], context_description="", org_id=None
    )

    id_a = await test_db.save_note(note_a)
    id_b = await test_db.save_note(note_b)
    id_null = await test_db.save_note(note_null)

    rows = await test_db.search_notes_by_keywords([kw], limit=10, org_id=org_a)
    ids = {r.id for r in rows}
    assert id_a in ids
    assert id_null in ids
    assert id_b not in ids
