"""Task 24: E2E LLM provider fallback + search-only degradation.

Tests the ``FallbackRouter`` cascade from ``tests/e2e/fixtures/llm.py``:

* One provider down → traffic rolls forward to the next; the answer
  surfaces text from whichever provider ultimately responds.
* All providers down → the pipeline degrades to search-only mode and
  emits the ``AI 답변 불가`` / ``검색만`` surface.
"""
from __future__ import annotations

import pytest

from breadmind.kb.query_pipeline import QueryPipeline
from tests.e2e.fixtures.llm import FallbackRouter, StubLLM


@pytest.mark.asyncio
async def test_anthropic_down_falls_back_to_azure(db, redis, slack):
    anth = StubLLM(provider="anthropic", model="claude-opus", fail_mode="down")
    az = StubLLM(provider="azure", model="gpt-4o",
                 script={"메모리 누수": "Azure 응답: CL 12345."})
    router = FallbackRouter([anth, az, StubLLM(provider="ollama", model="llama3")])
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=router)
    await pipe.handle_slack_mention(
        user_id="U-PILOT-00", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 결제 모듈 메모리 누수?",
    )
    assert "Azure 응답" in slack.posted[-1]["text"]


@pytest.mark.asyncio
async def test_all_providers_down_falls_back_to_search_only(db, redis, slack):
    downs = [StubLLM(provider=p, model="m", fail_mode="down")
             for p in ("anthropic", "azure", "ollama")]
    router = FallbackRouter(downs)
    pipe = QueryPipeline.build_for_e2e(db=db, redis=redis, slack=slack, llm=router)
    await pipe.handle_slack_mention(
        user_id="U-PILOT-00", channel_id="C-ALPHA-GENERAL",
        text="<@BREADMIND> 결제 모듈 메모리 누수?",
    )
    reply = slack.posted[-1]["text"]
    assert "AI 답변 불가" in reply or "검색만" in reply
