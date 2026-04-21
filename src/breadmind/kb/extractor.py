"""KnowledgeExtractor: LLM-driven promotion candidate extraction."""
from __future__ import annotations

import logging

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
