"""Shared utilities for SmartRetriever components."""

from __future__ import annotations

import re
from dataclasses import dataclass

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "and", "but", "or", "if", "while", "that", "this", "these", "those",
    "it", "its", "my", "your", "his", "her", "our", "their", "what",
    "which", "who", "whom", "check", "get", "set", "run", "use",
})

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9._-]+")


def _rrf_score(rank: int, k: int = 60) -> float:
    """Reciprocal Rank Fusion score. k=60 is the standard constant."""
    return 1.0 / (rank + k)


def extract_keywords(text: str) -> list[str]:
    """Extract keywords from text, filtering stopwords."""
    words = _WORD_PATTERN.findall(text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        if len(w) >= 2 and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result


@dataclass
class ScoredSkill:
    skill: object  # Skill from skill_store
    score: float
    token_estimate: int
    source: str  # "vector" | "kg" | "both"


@dataclass
class ContextItem:
    content: str
    score: float
    source: str  # "episodic" | "kg"
    token_estimate: int
