"""Company knowledge base (KB) foundation.

Public API (locked across P1-P5 plans):

- ``Redactor``, ``SecretDetected`` — PII/secret masking at the LLM boundary
- ``ACLResolver`` — project + Slack channel membership enforcement
- ``SensitiveClassifier``, ``SensitiveCategory`` — HR/Legal/etc blocking
- ``audit_log`` — insert into ``kb_audit_log``
"""
from __future__ import annotations

from .acl import ACLResolver
from .audit import audit_log
from .redactor import Redactor, SecretDetected
from .sensitive import SensitiveCategory, SensitiveClassifier

__all__ = [
    "ACLResolver",
    "Redactor",
    "SecretDetected",
    "SensitiveCategory",
    "SensitiveClassifier",
    "audit_log",
]
