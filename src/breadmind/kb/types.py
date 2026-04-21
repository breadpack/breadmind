from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Source:
    type: str
    uri: str
    ref: str | None = None


@dataclass
class KBHit:
    knowledge_id: int
    title: str
    body: str
    score: float
    sources: list[Source] = field(default_factory=list)


@dataclass
class EnforcedAnswer:
    text: str
    citations: list[Source]


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InsufficientEvidence(Exception):
    """Raised when CitationEnforcer cannot produce a supported answer."""
