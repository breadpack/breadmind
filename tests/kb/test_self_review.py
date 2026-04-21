# tests/kb/test_self_review.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.kb.self_review import SelfReviewer
from breadmind.kb.types import Confidence, KBHit, Source
from breadmind.llm.base import LLMResponse, TokenUsage


def _hit() -> KBHit:
    return KBHit(knowledge_id=1, title="t", body="b", score=0.8,
                 sources=[Source(type="confluence", uri="https://w/1")])


def _resp(text: str) -> LLMResponse:
    return LLMResponse(
        content=text, tool_calls=[],
        usage=TokenUsage(input_tokens=0, output_tokens=0), stop_reason="end",
    )


@pytest.mark.parametrize("verdict,expected", [
    ("STRONG", Confidence.LOW),
    ("WEAK", Confidence.HIGH),
    ("MODERATE", Confidence.MEDIUM),
])
async def test_confidence_from_verdict(verdict: str, expected: Confidence):
    router = MagicMock()
    router.chat = AsyncMock(return_value=_resp(
        f"counter-argument verdict: {verdict}. Reason: ..."
    ))
    reviewer = SelfReviewer(llm_router=router)
    out = await reviewer.score("the fix was cache eviction", [_hit()])
    assert out is expected


async def test_unparseable_verdict_defaults_low():
    router = MagicMock()
    router.chat = AsyncMock(return_value=_resp("????"))
    reviewer = SelfReviewer(llm_router=router)
    out = await reviewer.score("x", [_hit()])
    assert out is Confidence.LOW


async def test_no_hits_is_low():
    router = MagicMock()
    reviewer = SelfReviewer(llm_router=router)
    out = await reviewer.score("x", [])
    assert out is Confidence.LOW
    router.chat.assert_not_called()
