# tests/kb/test_citation.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.kb.citation import CitationEnforcer
from breadmind.kb.types import InsufficientEvidence, KBHit, Source
from breadmind.llm.base import LLMResponse, TokenUsage


def _hit(kid: int, title: str = "t", body: str = "b") -> KBHit:
    return KBHit(
        knowledge_id=kid, title=title, body=body, score=0.9,
        sources=[Source(type="confluence", uri=f"https://wiki/{kid}", ref=None)],
    )


async def test_draft_with_all_citations_passes_through():
    router = MagicMock()
    enf = CitationEnforcer(llm_router=router)
    hits = [_hit(1), _hit(2)]
    draft = "The leak was fixed [#1]. Run make payments [#2]."
    out = await enf.enforce(draft, hits)
    assert out.text == draft
    assert {c.uri for c in out.citations} == {"https://wiki/1", "https://wiki/2"}
    router.chat.assert_not_called()


def _llm_resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content, tool_calls=[],
        usage=TokenUsage(input_tokens=0, output_tokens=0), stop_reason="end",
    )


async def test_regenerates_once_when_uncited():
    router = MagicMock()
    router.chat = AsyncMock(return_value=_llm_resp(
        "Fixed by clearing cache [#1]."
    ))
    enf = CitationEnforcer(llm_router=router)
    hits = [_hit(1)]
    draft = "Fixed by clearing cache."  # no citation
    out = await enf.enforce(draft, hits)
    assert "[#1]" in out.text
    assert router.chat.await_count == 1


async def test_insufficient_evidence_after_second_failure():
    router = MagicMock()
    router.chat = AsyncMock(return_value=_llm_resp(
        "Still no citation."
    ))
    enf = CitationEnforcer(llm_router=router)
    hits = [_hit(1)]
    with pytest.raises(InsufficientEvidence):
        await enf.enforce("No citation here.", hits)
    assert router.chat.await_count == 1  # one retry only


async def test_rejects_fabricated_citation_id():
    router = MagicMock()
    # LLM invents [#999] which is not a real hit — treat as unsupported.
    router.chat = AsyncMock(return_value=_llm_resp("Answer [#999]."))
    enf = CitationEnforcer(llm_router=router)
    with pytest.raises(InsufficientEvidence):
        await enf.enforce("Answer.", [_hit(1)])
