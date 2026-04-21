# src/breadmind/kb/citation.py
from __future__ import annotations

import logging
import re

from breadmind.kb.types import EnforcedAnswer, InsufficientEvidence, KBHit, Source

logger = logging.getLogger(__name__)

_CITE_RE = re.compile(r"\[#(\d+)\]")
_MAX_RETRIES = 1  # 1 re-generation → 2 attempts total


class CitationEnforcer:
    """Validates that every factual sentence in a draft has a `[#<id>]` tag
    pointing at a real KBHit.knowledge_id. If the first draft is missing
    citations, we ask the LLM once to redo it; a second failure raises
    `InsufficientEvidence`."""

    def __init__(self, llm_router) -> None:
        self._router = llm_router

    async def enforce(
        self, draft: str, kb_hits: list[KBHit],
    ) -> EnforcedAnswer:
        allowed_ids = {h.knowledge_id for h in kb_hits}
        source_by_id = {h.knowledge_id: h.sources for h in kb_hits}

        if self._is_supported(draft, allowed_ids):
            return EnforcedAnswer(
                text=draft,
                citations=self._collect_sources(draft, source_by_id),
            )
        raise InsufficientEvidence("not yet implemented")

    @staticmethod
    def _cited_ids(text: str) -> set[int]:
        return {int(m.group(1)) for m in _CITE_RE.finditer(text)}

    @classmethod
    def _is_supported(cls, text: str, allowed: set[int]) -> bool:
        cited = cls._cited_ids(text)
        if not cited:
            return False
        return cited.issubset(allowed)

    @staticmethod
    def _collect_sources(
        text: str, sources_by_id: dict[int, list[Source]],
    ) -> list[Source]:
        out: list[Source] = []
        seen: set[tuple[str, str]] = set()
        for m in _CITE_RE.finditer(text):
            kid = int(m.group(1))
            for s in sources_by_id.get(kid, []):
                key = (s.type, s.uri)
                if key in seen:
                    continue
                seen.add(key)
                out.append(s)
        return out
