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
