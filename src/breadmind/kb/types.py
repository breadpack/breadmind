from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID


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


# ── P3 dataclasses ──────────────────────────────────────────────────────


@dataclass(slots=True)
class SourceMeta:
    source_type: str          # 'slack_msg' | 'confluence' | 'notion' | 'redmine' | 'p4_cl' | 'personal_kb'
    source_uri: str
    source_ref: str | None
    original_user: str | None
    project_id: UUID
    extracted_from: str       # e.g. 'slack_thread_resolved', 'confluence_sync', 'personal_nightly'


@dataclass(slots=True)
class ExtractedCandidate:
    proposed_title: str
    proposed_body: str
    proposed_category: str    # 'howto' | 'decision' | 'bug_fix' | 'onboarding' | 'sensitive_blocked'
    confidence: float         # 0.0..1.0
    sources: list[Source]
    original_user: str | None
    project_id: UUID
    sensitive_flag: bool = False


@dataclass(slots=True)
class PromotionCandidate:
    id: int
    project_id: UUID
    extracted_from: str
    original_user: str | None
    proposed_title: str
    proposed_body: str
    proposed_category: str
    sources_json: list[dict]
    confidence: float
    status: str               # 'pending'|'approved'|'rejected'|'needs_edit'
    reviewer: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None
    sensitive_flag: bool = False
