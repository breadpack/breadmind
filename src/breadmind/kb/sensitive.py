"""Sensitive-category classifier: keyword fast path + LLM slow path.

Categories: HR, LEGAL, FINANCE, SECURITY, PII.

- Fast path: case-insensitive substring match against ``keyword_map``.
- Slow path: only when text is moderately long AND no keyword matched,
  ask the LLM to label as one of the categories or ``NONE``. Any LLM
  error or unknown label returns ``None`` (fail-open on classification
  is safe; the pipeline's hard blocks stay in Redactor / explicit rules).
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

SLOW_PATH_MIN_CHARS = 120


class SensitiveCategory(str, Enum):
    HR = "HR"
    LEGAL = "LEGAL"
    FINANCE = "FINANCE"
    SECURITY = "SECURITY"
    PII = "PII"


_CLASSIFIER_PROMPT = (
    "Classify the user text into exactly one label: "
    "HR, LEGAL, FINANCE, SECURITY, PII, or NONE. "
    "Reply with only the label, nothing else.\n\nText:\n{text}"
)


class SensitiveClassifier:
    def __init__(
        self,
        llm_router: Any,
        keyword_map: dict[SensitiveCategory, list[str]],
    ):
        self._llm = llm_router
        self._keyword_map = {
            cat: [kw.lower() for kw in kws]
            for cat, kws in keyword_map.items()
        }

    async def classify(self, text: str) -> SensitiveCategory | None:
        lower = text.lower()
        for cat, kws in self._keyword_map.items():
            for kw in kws:
                if kw in lower:
                    return cat
        if len(text) < SLOW_PATH_MIN_CHARS:
            return None
        try:
            raw = await self._llm.generate(
                _CLASSIFIER_PROMPT.format(text=text)
            )
        except Exception as exc:
            logger.warning("sensitive slow-path LLM failed: %s", exc)
            return None
        label = (raw or "").strip().upper()
        if label in {c.value for c in SensitiveCategory}:
            return SensitiveCategory(label)
        return None
