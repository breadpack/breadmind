"""KnowledgeExtractor: LLM-driven promotion candidate extraction."""
from __future__ import annotations

import json
import logging

from breadmind.kb.types import ExtractedCandidate, Source, SourceMeta

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {"howto", "decision", "bug_fix", "onboarding"}
_CONFIDENCE_FLOOR = 0.6
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 100


def _chunk(text: str, *, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split ``text`` into fixed-width overlapping chunks.

    Returns an empty list for empty input. Raises ``ValueError`` for
    non-positive ``size`` or ``overlap`` outside ``[0, size)``.
    """
    if not text:
        return []
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")
    stride = size - overlap
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += stride
    return out


EXTRACTOR_PROMPT = """You are extracting reusable organizational knowledge candidates.

Content:
{content}

Return STRICT JSON of the form:
{{"candidates": [
  {{"proposed_title": "...",
    "proposed_body": "...",
    "proposed_category": "howto|decision|bug_fix|onboarding",
    "confidence": 0.0-1.0}}
]}}

Rules:
- Only include items that are genuinely reusable by other teammates.
- If nothing qualifies, return {{"candidates": []}}.
- Do not invent facts that are not in the content.
"""


class KnowledgeExtractor:
    """Extract promotion candidates from content using an LLM + sensitivity gate."""

    def __init__(self, llm_router, sensitive) -> None:
        self._llm = llm_router
        self._sensitive = sensitive

    async def extract(
        self,
        content: str,
        source_meta: SourceMeta,
    ) -> list[ExtractedCandidate]:
        if not content or not content.strip():
            return []

        chunks = _chunk(content)
        out: list[ExtractedCandidate] = []

        for chunk in chunks:
            try:
                raw = await self._llm.complete(
                    EXTRACTOR_PROMPT.format(content=chunk),
                    temperature=0.0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("extractor LLM call failed: %s", exc)
                continue

            try:
                data = json.loads(raw)
                items = data.get("candidates", []) if isinstance(data, dict) else []
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("extractor returned non-JSON: %s", exc)
                continue

            for item in items:
                cand = await self._build_candidate(item, source_meta)
                if cand is not None:
                    out.append(cand)

        return out

    async def _build_candidate(
        self,
        item: dict,
        meta: SourceMeta,
    ) -> ExtractedCandidate | None:
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            return None
        if confidence < _CONFIDENCE_FLOOR:
            return None

        category = str(item.get("proposed_category", ""))
        if category not in _VALID_CATEGORIES:
            return None

        title = str(item.get("proposed_title", "")).strip()
        body = str(item.get("proposed_body", "")).strip()
        if not title or not body:
            return None

        # Sensitivity gate (fail-closed on classifier error)
        try:
            is_sensitive = await self._sensitive.is_sensitive(f"{title}\n{body}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("sensitive classifier error, treating as sensitive: %s", exc)
            is_sensitive = True

        # Build a Source from SourceMeta using the REAL field names (type/uri/ref).
        source = Source(
            type=meta.source_type,
            uri=meta.source_uri,
            ref=meta.source_ref,
        )

        return ExtractedCandidate(
            proposed_title=title,
            proposed_body=body,
            proposed_category="sensitive_blocked" if is_sensitive else category,
            confidence=confidence,
            sources=[source],
            original_user=meta.original_user,
            project_id=meta.project_id,
            sensitive_flag=is_sensitive,
        )
