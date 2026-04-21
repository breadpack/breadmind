# tests/kb/test_citation.py
from unittest.mock import MagicMock

from breadmind.kb.citation import CitationEnforcer
from breadmind.kb.types import KBHit, Source


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
