# src/breadmind/kb/citation.py
from __future__ import annotations

import logging
import re

from breadmind.kb.types import EnforcedAnswer, InsufficientEvidence, KBHit, Source
from breadmind.llm.base import LLMMessage

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

        current = draft
        attempts = 0
        while True:
            if self._is_supported(current, allowed_ids):
                return EnforcedAnswer(
                    text=current,
                    citations=self._collect_sources(current, source_by_id),
                )
            if attempts >= _MAX_RETRIES:
                logger.info("CitationEnforcer giving up after %d retries", attempts)
                raise InsufficientEvidence(
                    "Draft not supported by provided KB hits after retry"
                )
            attempts += 1
            current = await self._regenerate(current, kb_hits)

    async def _regenerate(self, draft: str, hits: list[KBHit]) -> str:
        snippets = "\n".join(
            f"[#{h.knowledge_id}] {h.title}: {h.body[:400]}" for h in hits
        )
        system = (
            "You MUST cite every factual claim with [#<id>] referencing "
            "only the IDs listed below. Do NOT invent IDs. If a claim "
            "cannot be supported by any listed snippet, drop the claim."
        )
        user = (
            f"KB snippets:\n{snippets}\n\n"
            f"Original draft (missing citations):\n{draft}\n\n"
            f"Rewrite the answer with [#<id>] citations on every factual sentence."
        )
        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]
        resp = await self._router.chat(messages)
        return resp.content or ""

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
