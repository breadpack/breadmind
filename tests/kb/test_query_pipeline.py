# tests/kb/test_query_pipeline.py
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from breadmind.kb.query_pipeline import QueryPipeline
from breadmind.kb.types import Confidence, EnforcedAnswer, KBHit, Source
from breadmind.llm.base import LLMResponse, TokenUsage
from breadmind.messenger.router import IncomingMessage


def _hit() -> KBHit:
    return KBHit(
        knowledge_id=1, title="fix", body="clear cache", score=0.9,
        sources=[Source(type="slack_msg", uri="https://slack/p1", ref="ts")],
    )


def _llm(text: str) -> LLMResponse:
    return LLMResponse(
        content=text, tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=20), stop_reason="end",
    )


def _pipeline_with_mocks(fake_redis):
    retriever = MagicMock()
    retriever.search = AsyncMock(return_value=[_hit()])

    redactor = MagicMock()
    redactor.redact.return_value = ("masked query", {"<USER_1>": "U_ALICE"})
    redactor.abort_if_secrets.return_value = None
    redactor.restore.side_effect = lambda text, _map: text

    router = MagicMock()
    router.chat = AsyncMock(return_value=_llm("clear cache [#1]"))

    citer = MagicMock()
    citer.enforce = AsyncMock(
        return_value=EnforcedAnswer(text="clear cache [#1]",
                                    citations=_hit().sources)
    )
    reviewer = MagicMock()
    reviewer.score = AsyncMock(return_value=Confidence.HIGH)

    sensitive = MagicMock()
    sensitive.classify.return_value = None

    from breadmind.kb.query_cache import QueryCache
    from breadmind.kb.quota import QuotaTracker
    cache = QueryCache(redis=fake_redis)
    quota = QuotaTracker(redis=fake_redis)

    pipeline = QueryPipeline(
        retriever=retriever,
        redactor=redactor,
        llm_router=router,
        citer=citer,
        reviewer=reviewer,
        sensitive=sensitive,
        cache=cache,
        quota=quota,
        project_resolver=AsyncMock(return_value=uuid4()),
    )
    return pipeline, {"retriever": retriever, "router": router, "citer": citer,
                      "reviewer": reviewer, "redactor": redactor,
                      "sensitive": sensitive, "cache": cache, "quota": quota}


async def test_happy_path(fake_redis):
    pipeline, mocks = _pipeline_with_mocks(fake_redis)
    inc = IncomingMessage(
        text="how was the leak fixed?",
        user_id="U_ALICE", channel_id="C1", platform="slack",
    )
    out = await pipeline.answer(inc)
    assert "clear cache" in out.text
    assert "https://slack/p1" in out.text  # permalink formatted
    mocks["retriever"].search.assert_awaited()
    mocks["citer"].enforce.assert_awaited()


async def test_sensitive_category_blocks_early(fake_redis):
    pipeline, mocks = _pipeline_with_mocks(fake_redis)
    mocks["sensitive"].classify.return_value = "hr_evaluation"
    inc = IncomingMessage(
        text="Show me John's salary", user_id="U_ALICE",
        channel_id="C1", platform="slack",
    )
    out = await pipeline.answer(inc)
    assert "민감" in out.text or "sensitive" in out.text.lower()
    mocks["retriever"].search.assert_not_awaited()
    mocks["router"].chat.assert_not_awaited()


async def test_quota_exceeded_downgrades_to_search_only(fake_redis):
    pipeline, mocks = _pipeline_with_mocks(fake_redis)
    await mocks["quota"].charge("U_ALICE", 10_000_000)
    inc = IncomingMessage(
        text="how was the leak fixed?", user_id="U_ALICE",
        channel_id="C1", platform="slack",
    )
    out = await pipeline.answer(inc)
    assert "검색만" in out.text or "search-only" in out.text.lower()
    # retriever runs (we still show KB links), LLM does NOT
    mocks["retriever"].search.assert_awaited()
    mocks["router"].chat.assert_not_awaited()
    assert "https://slack/p1" in out.text


async def test_cache_hit_short_circuits(fake_redis):
    pipeline, mocks = _pipeline_with_mocks(fake_redis)
    await mocks["cache"].set("q", "U_ALICE", "PROJ", "cached-body")
    # pin project resolver to a known id so cache key matches
    from uuid import UUID
    pid = UUID("11111111-1111-1111-1111-111111111111")
    pipeline._project_resolver = AsyncMock(return_value=pid)
    # precompute cache under that project id
    await mocks["cache"].set("how was the leak fixed?", "U_ALICE", str(pid),
                             "cached-body")
    inc = IncomingMessage(
        text="how was the leak fixed?", user_id="U_ALICE",
        channel_id="C1", platform="slack",
    )
    out = await pipeline.answer(inc)
    assert "cached-body" in out.text
    mocks["retriever"].search.assert_not_awaited()
    mocks["router"].chat.assert_not_awaited()


async def test_insufficient_evidence_falls_back_to_top3(fake_redis):
    from breadmind.kb.types import InsufficientEvidence
    pipeline, mocks = _pipeline_with_mocks(fake_redis)
    mocks["citer"].enforce = AsyncMock(
        side_effect=InsufficientEvidence("no support")
    )
    inc = IncomingMessage(
        text="obscure question", user_id="U_ALICE",
        channel_id="C1", platform="slack",
    )
    out = await pipeline.answer(inc)
    assert "확실한 답변 불가" in out.text or "근거" in out.text
    assert "https://slack/p1" in out.text
