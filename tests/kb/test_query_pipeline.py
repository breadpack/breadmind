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
