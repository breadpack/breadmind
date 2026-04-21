"""Company knowledge base (KB) — P1 Foundation + P2 Query Path.

Public API (locked across P1-P5 plans):

P1:
- ``Redactor``, ``SecretDetected`` — PII/secret masking at the LLM boundary
- ``ACLResolver`` — project + Slack channel membership enforcement
- ``SensitiveClassifier``, ``SensitiveCategory`` — HR/Legal/etc blocking
- ``audit_log`` — insert into ``kb_audit_log``

P2:
- ``CitationEnforcer`` — enforce citation presence in LLM answers
- ``KBRetriever`` — hybrid retrieval (vector + BM25)
- ``QueryCache`` — Redis-backed query result cache
- ``QueryPipeline`` — full end-to-end query orchestrator
- ``QuotaTracker`` — per-user daily token quota
- ``SelfReviewer`` — LLM self-review for confidence scoring

Shared types:
- ``Confidence``, ``EnforcedAnswer``, ``InsufficientEvidence``, ``KBHit``,
  ``Source``
"""
from __future__ import annotations

from .acl import ACLResolver
from .audit import audit_log
from .citation import CitationEnforcer
from .query_cache import QueryCache
from .query_pipeline import QueryPipeline
from .quota import QuotaTracker
from .redactor import Redactor, SecretDetected
from .retriever import KBRetriever
from .self_review import SelfReviewer
from .sensitive import SensitiveCategory, SensitiveClassifier
from .types import Confidence, EnforcedAnswer, InsufficientEvidence, KBHit, Source

__all__ = [
    "ACLResolver",
    "CitationEnforcer",
    "Confidence",
    "EnforcedAnswer",
    "InsufficientEvidence",
    "KBHit",
    "KBRetriever",
    "QueryCache",
    "QueryPipeline",
    "QuotaTracker",
    "Redactor",
    "SecretDetected",
    "SelfReviewer",
    "SensitiveCategory",
    "SensitiveClassifier",
    "Source",
    "audit_log",
]
