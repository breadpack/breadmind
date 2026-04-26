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
