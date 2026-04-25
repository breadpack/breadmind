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
