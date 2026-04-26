"""Defensive PII / credential redactor for EpisodicRecorder LLM inputs.

Section 13 follow-up: ``episodic_normalize.j2`` is rendered with Jinja
autoescape OFF (intentional — the LLM consumes raw text). Before any
text-bearing field on a ``SignalEvent`` is interpolated into that prompt,
``redact()`` masks common PII / credential shapes with stable tokens so
secrets never reach the recorder's normalization LLM.

Tokens are stable so the output is idempotent — ``redact(redact(x)) == redact(x)``.
"""

from __future__ import annotations

import re

__all__ = ["redact"]


# ---------------------------------------------------------------------------
# Pattern table
# ---------------------------------------------------------------------------
#
# Order matters: more specific patterns run first so that, e.g., a JWT inside
# an `Authorization: Bearer …` header is masked as `[JWT]` rather than the
# generic `[BEARER]` token.
#
# Each entry is (regex, replacement). All regexes are pre-compiled once at
# module import.

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)

_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{12,16}\b")

# Bearer-style: only inside Authorization:/Bearer prefix. Matches the token
# (hex or base64-ish) of length >= 32. Anchoring on the prefix avoids eating
# git SHAs, SRI hashes, and other long hex blobs that look credential-shaped
# but are not.
_BEARER_RE = re.compile(
    r"(?P<prefix>(?:Authorization:\s*(?:Bearer\s+)?|Bearer\s+))"
    r"(?P<tok>[A-Za-z0-9+/=_\-]{32,})"
)

# IPv4 with negative skip for loopback / unspecified addresses (kept for
# debuggability per spec). We mask the dotted-quad and then restore the two
# debug-friendly literals if they were on the skip list.
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV4_SKIP: frozenset[str] = frozenset({"0.0.0.0", "127.0.0.1"})


def _mask_ipv4(match: re.Match[str]) -> str:
    addr = match.group(0)
    if addr in _IPV4_SKIP:
        return addr
    # Validate octet ranges (regex above is lenient — 999.999.999.999 matches).
    parts = addr.split(".")
    try:
        if all(0 <= int(p) <= 255 for p in parts):
            return "[IPV4]"
    except ValueError:  # pragma: no cover - regex guarantees digits
        pass
    return addr


def _mask_bearer(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[BEARER]"


def redact(text: str) -> str:
    """Replace common PII / credential patterns with stable masked tokens.

    Patterns masked:

    * ``[EMAIL]``  — RFC-ish email addresses
    * ``[IPV4]``   — dotted-quad IPv4 (excluding ``0.0.0.0`` and ``127.0.0.1``)
    * ``[JWT]``    — three-segment ``eyJ…`` tokens
    * ``[AWS_KEY]``— ``AKIA``-prefixed access key ids
    * ``[BEARER]`` — long token following ``Authorization:``/``Bearer ``

    Idempotent: ``redact(redact(x)) == redact(x)``.

    The function expects ``text`` to be a ``str``; passing ``None`` is not
    supported — callers should coerce or skip empty fields themselves.
    """
    if not text:
        return text
    # Order: high-specificity credential shapes first, then the bearer
    # catch-all (whose anchor would also match a JWT), finally email and IP.
    text = _AWS_KEY_RE.sub("[AWS_KEY]", text)
    text = _JWT_RE.sub("[JWT]", text)
    text = _BEARER_RE.sub(_mask_bearer, text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _IPV4_RE.sub(_mask_ipv4, text)
    return text
