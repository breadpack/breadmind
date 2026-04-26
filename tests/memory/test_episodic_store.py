import uuid
import pytest
from breadmind.memory.episodic_store import (
    PostgresEpisodicStore, EpisodicFilter,
)
from breadmind.memory.event_types import SignalKind
from breadmind.storage.models import EpisodicNote


def _uid() -> str:
    """Return a unique user-id prefix so each test run is isolated from prior DB state."""
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_search_filters_by_user_and_tool(test_db):
    store = PostgresEpisodicStore(test_db)
    alice = _uid()
    bob = _uid()
    await store.write(EpisodicNote(
        content="a", keywords=["vpc"], tags=[], context_description="",
        kind="tool_executed", tool_name="aws_vpc_create",
        tool_args_digest="aaaa1111", outcome="success",
        user_id=alice, summary="vpc created",
    ))
    await store.write(EpisodicNote(
        content="b", keywords=["vpc"], tags=[], context_description="",
        kind="tool_executed", tool_name="aws_vpc_create",
        tool_args_digest="aaaa1111", outcome="success",
        user_id=bob, summary="bob's vpc",
    ))
    res = await store.search(
        user_id=alice, query=None,
        filters=EpisodicFilter(tool_name="aws_vpc_create"),
        limit=5,
    )
    assert len(res) == 1
    assert res[0].user_id == alice


@pytest.mark.asyncio
async def test_search_orders_by_digest_then_recency(test_db):
    store = PostgresEpisodicStore(test_db)
    alice = _uid()
    older = EpisodicNote(
        content="o", keywords=["x"], tags=[], context_description="",
        kind="tool_executed", tool_name="t", tool_args_digest="aaaa1111",
        outcome="success", user_id=alice, summary="older",
    )
    newer = EpisodicNote(
        content="n", keywords=["x"], tags=[], context_description="",
        kind="tool_executed", tool_name="t", tool_args_digest="bbbb2222",
        outcome="failure", user_id=alice, summary="newer",
    )
    await store.write(older)
    await store.write(newer)

    # When digest matches "aaaa1111", that note must come first even though it's older.
    res = await store.search(
        user_id=alice, query=None,
        filters=EpisodicFilter(
            tool_name="t",
            tool_args_digest="aaaa1111",
            kinds=[SignalKind.TOOL_EXECUTED, SignalKind.TOOL_FAILED],
        ),
        limit=5,
    )
    assert res[0].summary == "older"


@pytest.mark.asyncio
async def test_search_keyword_array_overlap(test_db):
    store = PostgresEpisodicStore(test_db)
    alice = _uid()
    await store.write(EpisodicNote(
        content="c", keywords=["vpc", "subnet"], tags=[],
        context_description="", user_id=alice, summary="kw match",
    ))
    res = await store.search(
        user_id=alice, query=None,
        filters=EpisodicFilter(keywords=["subnet"]),
        limit=5,
    )
    assert any(r.summary == "kw match" for r in res)


@pytest.mark.asyncio
async def test_search_query_string_extracts_keywords(test_db):
    store = PostgresEpisodicStore(test_db)
    alice = _uid()
    await store.write(EpisodicNote(
        content="z", keywords=["vpc"], tags=[], context_description="",
        user_id=alice, summary="from query",
    ))
    res = await store.search(
        user_id=alice, query="어제 그 VPC 어떻게 됐지?",
        filters=EpisodicFilter(),
        limit=5,
    )
    assert any(r.summary == "from query" for r in res)


# ── T4: EpisodicFilter.org_id + store.search SQL isolation ───────────────────


@pytest.mark.asyncio
async def test_search_org_id_none_returns_all(test_db, insert_org):
    """org_id=None filter → no org clause → all matching notes regardless of org_id."""
    store = PostgresEpisodicStore(test_db)
    org_a = uuid.uuid4()
    await insert_org(org_a)
    kw = f"orgfilt_none_{uuid.uuid4().hex[:6]}"

    id_with_org = await store.write(EpisodicNote(
        content="has org", keywords=[kw], tags=[], context_description="",
        org_id=org_a,
    ))
    id_no_org = await store.write(EpisodicNote(
        content="no org", keywords=[kw], tags=[], context_description="",
        org_id=None,
    ))

    res = await store.search(
        user_id=None, query=None,
        filters=EpisodicFilter(keywords=[kw], org_id=None),
        limit=10,
    )
    ids = {r.id for r in res}
    assert id_with_org in ids
    assert id_no_org in ids


@pytest.mark.asyncio
async def test_search_org_id_uuid_permissive(test_db, insert_org):
    """UUID filter (permissive default) → org's notes PLUS NULL-org notes; other org excluded."""
    store = PostgresEpisodicStore(test_db)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    await insert_org(org_a)
    await insert_org(org_b)
    kw = f"orgfilt_perm_{uuid.uuid4().hex[:6]}"

    id_a = await store.write(EpisodicNote(
        content="org a note", keywords=[kw], tags=[], context_description="",
        org_id=org_a,
    ))
    id_b = await store.write(EpisodicNote(
        content="org b note", keywords=[kw], tags=[], context_description="",
        org_id=org_b,
    ))
    id_null = await store.write(EpisodicNote(
        content="legacy note", keywords=[kw], tags=[], context_description="",
        org_id=None,
    ))

    res = await store.search(
        user_id=None, query=None,
        filters=EpisodicFilter(keywords=[kw], org_id=org_a),
        limit=10,
    )
    ids = {r.id for r in res}
    assert id_a in ids
    assert id_null in ids
    assert id_b not in ids


@pytest.mark.asyncio
async def test_search_org_id_cross_org_isolation(test_db, insert_org):
    """Two distinct UUIDs: org_a filter does NOT return org_b notes; NULL notes returned."""
    store = PostgresEpisodicStore(test_db)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    await insert_org(org_a)
    await insert_org(org_b)
    kw = f"orgfilt_iso_{uuid.uuid4().hex[:6]}"

    id_a = await store.write(EpisodicNote(
        content="a", keywords=[kw], tags=[], context_description="", org_id=org_a,
    ))
    id_b = await store.write(EpisodicNote(
        content="b", keywords=[kw], tags=[], context_description="", org_id=org_b,
    ))
    id_null = await store.write(EpisodicNote(
        content="null", keywords=[kw], tags=[], context_description="", org_id=None,
    ))

    res_a = await store.search(
        user_id=None, query=None,
        filters=EpisodicFilter(keywords=[kw], org_id=org_a),
        limit=10,
    )
    ids_a = {r.id for r in res_a}
    assert id_a in ids_a
    assert id_null in ids_a
    assert id_b not in ids_a

    res_b = await store.search(
        user_id=None, query=None,
        filters=EpisodicFilter(keywords=[kw], org_id=org_b),
        limit=10,
    )
    ids_b = {r.id for r in res_b}
    assert id_b in ids_b
    assert id_null in ids_b
    assert id_a not in ids_b


@pytest.mark.asyncio
async def test_search_org_id_strict_mode(test_db, insert_org, monkeypatch):
    """Strict mode (BREADMIND_EPISODIC_STRICT_ORG=1) → NULL-org notes excluded from results."""
    monkeypatch.setenv("BREADMIND_EPISODIC_STRICT_ORG", "1")
    store = PostgresEpisodicStore(test_db)
    org_a = uuid.uuid4()
    await insert_org(org_a)
    kw = f"orgfilt_strict_{uuid.uuid4().hex[:6]}"

    id_a = await store.write(EpisodicNote(
        content="org a strict", keywords=[kw], tags=[], context_description="",
        org_id=org_a,
    ))
    id_null = await store.write(EpisodicNote(
        content="legacy strict", keywords=[kw], tags=[], context_description="",
        org_id=None,
    ))

    res = await store.search(
        user_id=None, query=None,
        filters=EpisodicFilter(keywords=[kw], org_id=org_a),
        limit=10,
    )
    ids = {r.id for r in res}
    assert id_a in ids
    assert id_null not in ids
