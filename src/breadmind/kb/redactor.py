"""PII / secret redactor — single guard at the LLM boundary.

Patterns (ordered):

1. ``abort_if_secrets()`` — API keys, high-entropy tokens, credit card
   (Luhn), SSN. Raises :class:`SecretDetected`; caller must NOT call
   the LLM.
2. ``redact()`` — email, phone, Slack user id, Perforce depot path,
   internal-domain URL, vocab-based client names. Each match becomes
   ``<KIND_N>`` and the reverse map is stored in Redis under
   ``redact:map:<map_id>`` with TTL 2h. Returns ``(masked, map_id)``.
3. ``restore()`` — reverse ``<KIND_N>`` back to the original. If the
   map has expired the input is returned unchanged.
"""
from __future__ import annotations

import json
import math
import re
import secrets
from collections import Counter

REDACT_TTL_SECONDS = 2 * 60 * 60


class SecretDetected(Exception):
    """Raised when text contains a hard-block secret pattern."""


_API_KEY_PATTERNS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[aboprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
]
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-().]{7,}\d")
_SLACK_USER_RE = re.compile(r"<@([UW][A-Z0-9]{6,})>|\b([UW][A-Z0-9]{8,})\b")
_P4_PATH_RE = re.compile(r"//[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if len(d) < 13 or len(d) > 19:
        return False
    checksum = 0
    parity = len(d) % 2
    for i, n in enumerate(d):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        checksum += n
    return checksum % 10 == 0


class Redactor:
    """Mask PII/client-identifying tokens; abort on hard secrets."""

    internal_domains: set[str]

    def __init__(self, redis, vocab: list[str]):
        self._redis = redis
        self._vocab = sorted(
            {v for v in vocab if v}, key=len, reverse=True
        )
        self.internal_domains = set()

    async def abort_if_secrets(self, text: str) -> None:
        for pat in _API_KEY_PATTERNS:
            if pat.search(text):
                raise SecretDetected("api key / token pattern matched")
        for match in _CC_RE.findall(text):
            if _luhn_ok(match):
                raise SecretDetected("credit card number (Luhn)")
        if _SSN_RE.search(text):
            raise SecretDetected("SSN pattern matched")
        for token in re.findall(r"\S{24,}", text):
            if _shannon_entropy(token) >= 4.5:
                raise SecretDetected("high-entropy token")

    async def redact(self, text: str, session_id: str) -> tuple[str, str]:
        mapping: dict[str, str] = {}
        counters: dict[str, int] = {}

        def _next(kind: str) -> str:
            counters[kind] = counters.get(kind, 0) + 1
            return f"<{kind}_{counters[kind]}>"

        def _sub_regex(pattern: re.Pattern, kind: str, s: str) -> str:
            def repl(m: re.Match) -> str:
                orig = m.group(0)
                token = _next(kind)
                mapping[token] = orig
                return token
            return pattern.sub(repl, s)

        def _sub_url(s: str) -> str:
            def repl(m: re.Match) -> str:
                url = m.group(0)
                if any(d in url for d in self.internal_domains):
                    token = _next("INTERNAL_URL")
                    mapping[token] = url
                    return token
                return url
            return _URL_RE.sub(repl, s)

        def _sub_slack_user(s: str) -> str:
            def repl(m: re.Match) -> str:
                orig = m.group(0)
                token = _next("USER")
                mapping[token] = orig
                return token
            return _SLACK_USER_RE.sub(repl, s)

        def _sub_vocab(s: str) -> str:
            for term in self._vocab:
                if term and term in s:
                    token = _next("CLIENT")
                    mapping[token] = term
                    s = s.replace(term, token)
            return s

        out = text
        out = _sub_regex(_EMAIL_RE, "EMAIL", out)
        out = _sub_regex(_PHONE_RE, "PHONE", out)
        out = _sub_slack_user(out)
        out = _sub_url(out)
        out = _sub_regex(_P4_PATH_RE, "P4_PATH", out)
        out = _sub_vocab(out)

        map_id = f"{session_id}:{secrets.token_hex(8)}"
        if mapping:
            await self._redis.set(
                f"redact:map:{map_id}",
                json.dumps(mapping),
                ex=REDACT_TTL_SECONDS,
            )
        return out, map_id

    async def restore(self, text: str, map_id: str) -> str:
        raw = await self._redis.get(f"redact:map:{map_id}")
        if raw is None:
            return text
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        mapping: dict[str, str] = json.loads(raw)
        out = text
        for token, original in mapping.items():
            out = out.replace(token, original)
        return out
