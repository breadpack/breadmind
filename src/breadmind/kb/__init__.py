"""Company knowledge base (KB) foundation.

Public API (locked across P1-P5 plans):

- ``Redactor``, ``SecretDetected`` — PII/secret masking at the LLM boundary
- ``ACLResolver`` — project + Slack channel membership enforcement
- ``SensitiveClassifier``, ``SensitiveCategory`` — HR/Legal/etc blocking
- ``audit_log`` — insert into ``kb_audit_log``
- ``Confidence``, ``EnforcedAnswer``, ``InsufficientEvidence``, ``KBHit``,
  ``Source`` — shared query-path types
"""
from __future__ import annotations

from .acl import ACLResolver
from .audit import audit_log
from .redactor import Redactor, SecretDetected
from .sensitive import SensitiveCategory, SensitiveClassifier
from .types import Confidence, EnforcedAnswer, InsufficientEvidence, KBHit, Source

__all__ = [
    "ACLResolver",
    "Confidence",
    "EnforcedAnswer",
    "InsufficientEvidence",
    "KBHit",
    "Redactor",
    "SecretDetected",
    "SensitiveCategory",
    "SensitiveClassifier",
    "Source",
    "audit_log",
]
