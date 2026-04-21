# src/breadmind/kb/self_review.py
from __future__ import annotations

import logging
import re

from breadmind.kb.types import Confidence, KBHit
from breadmind.llm.base import LLMMessage

logger = logging.getLogger(__name__)

_VERDICT_RE = re.compile(r"verdict\s*:\s*(STRONG|MODERATE|WEAK)", re.IGNORECASE)


class SelfReviewer:
    """Prompts the LLM with an adversarial 'why might this be wrong?' query
    and maps verdict strength to a Confidence level.

    Mapping:
      STRONG counter-argument → Confidence.LOW   (likely wrong)
      MODERATE               → Confidence.MEDIUM
      WEAK                   → Confidence.HIGH   (answer holds)

    Called only when the caller wants a review — `QueryPipeline` skips it when
    every confidence signal upstream is already strong (§8.6 cost control).
    """

    def __init__(self, llm_router) -> None:
        self._router = llm_router

    async def score(
        self, answer: str, kb_hits: list[KBHit],
    ) -> Confidence:
        if not kb_hits:
            return Confidence.LOW

        snippets = "\n".join(
            f"[#{h.knowledge_id}] {h.title}: {h.body[:300]}" for h in kb_hits
        )
        system = (
            "You are an adversarial reviewer. Given an answer and the KB "
            "snippets it is based on, construct the strongest counter-argument "
            "for why the answer could be wrong. Reply with a single line: "
            "'verdict: <STRONG|MODERATE|WEAK>. Reason: <one sentence>.'"
        )
        user = f"Answer:\n{answer}\n\nKB snippets:\n{snippets}"
        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]
        resp = await self._router.chat(messages)
        text = resp.content or ""
        m = _VERDICT_RE.search(text)
        if not m:
            logger.info("SelfReviewer could not parse verdict: %r", text[:120])
            return Confidence.LOW
        verdict = m.group(1).upper()
        if verdict == "STRONG":
            return Confidence.LOW
        if verdict == "WEAK":
            return Confidence.HIGH
        return Confidence.MEDIUM
