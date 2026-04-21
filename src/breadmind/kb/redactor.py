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
import logging
import math
import re
import secrets
from collections import Counter

from breadmind.kb import metrics as kb_metrics

REDACT_TTL_SECONDS = 2 * 60 * 60

logger = logging.getLogger(__name__)


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
# Atomic group prevents catastrophic backtracking on long digit runs
# (timestamps, log IDs). Atomic groups available in Python 3.11+.
_CC_RE = re.compile(r"\b(?>(?:\d[ -]?){13,19})\b")


# Named PII pattern registry — used by ``redact_prompt`` for metric
# labelling. The keys appear verbatim as the ``pattern`` label on
# ``breadmind_redaction_events_total``.
_NAMED_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", _EMAIL_RE),
    ("phone", _PHONE_RE),
    ("slack_user", _SLACK_USER_RE),
    ("p4_path", _P4_PATH_RE),
    ("ssn", _SSN_RE),
    ("url", _URL_RE),
)
_API_KEY_PATTERN_LABEL = "api_key"


# Sensitive-category keyword table. Each category emits a single
# ``breadmind_block_sensitive_total{category=...}`` counter bump when
# any keyword matches (case-insensitive substring). Keys are stable
# spec labels — do not rename without coordinating with dashboards.
_SENSITIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hr_compensation": (
        "연봉", "급여", "보너스", "인센티브", "스톡옵션",
        "salary", "compensation", "bonus", "payroll",
    ),
    "hr_evaluation": (
        "평가", "인사고과", "고과", "review score",
        "performance review",
    ),
    "legal_litigation": (
        "소송", "제소", "litigation", "lawsuit", "legal dispute",
    ),
    "security_credentials": (
        "비밀번호", "password", "비밀키", "secret key",
    ),
}


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
        # Min length 24 ≈ shortest plausible API key/token.
        # Entropy >= 4.5 bits/char ≈ base64-like density; below this most
        # natural-language tokens of any length stay under threshold.
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

    # ─── metric-emitting scan helpers ─────────────────────────────────
    # These are synchronous scan-only methods intended for the P5 ops
    # path that emits Prometheus counters. They do NOT persist a restore
    # map (use :meth:`redact` for that). The async ``redact`` is still
    # the production boundary guard at the LLM edge.

    @classmethod
    def default(cls) -> "Redactor":
        """Return a Redactor with an in-memory redis stub + empty vocab.

        Used by test harnesses and the ``redact_prompt`` / ``check_sensitive``
        metric paths which do not need a real Redis map store.
        """
        return cls(redis=_NullRedis(), vocab=[])

    def redact_prompt(self, text: str) -> str:
        """Scan ``text`` for known PII/secret patterns, emitting a
        ``breadmind_redaction_events_total{pattern=...}`` counter bump
        for each matching pattern. Returns a best-effort masked string
        (each matched substring replaced by ``<PATTERN>``) for callers
        that want a redacted preview; callers persisting a restore map
        should use :meth:`redact` instead.
        """
        out = text
        # Secrets first: API key pattern family collapses to a single
        # ``api_key`` label regardless of which concrete regex matched
        # (label cardinality budget — the family is ~5 regexes).
        for pat in _API_KEY_PATTERNS:
            if pat.search(out):
                try:
                    kb_metrics.observe_redaction(
                        pattern=_API_KEY_PATTERN_LABEL,
                    )
                except Exception:  # pragma: no cover — defensive
                    logger.exception("observe_redaction(api_key) failed")
                out = pat.sub(f"<{_API_KEY_PATTERN_LABEL.upper()}>", out)
                break  # count the family once per call

        for name, pat in _NAMED_PATTERNS:
            if pat.search(out):
                try:
                    kb_metrics.observe_redaction(pattern=name)
                except Exception:  # pragma: no cover
                    logger.exception("observe_redaction(%s) failed", name)
                out = pat.sub(f"<{name.upper()}>", out)
        return out

    def check_sensitive(self, text: str) -> str | None:
        """Return the first matching sensitive category (by spec label),
        or ``None`` if the text is clean. Emits a
        ``breadmind_block_sensitive_total{category=...}`` counter bump on
        match so ops dashboards can track sensitive-class blocks.
        """
        lower = text.lower()
        for category, keywords in _SENSITIVE_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in lower:
                    try:
                        kb_metrics.observe_block_sensitive(category=category)
                    except Exception:  # pragma: no cover
                        logger.exception(
                            "observe_block_sensitive(%s) failed", category,
                        )
                    return category
        return None


class _NullRedis:
    """Minimal Redis stub used by :meth:`Redactor.default`.

    ``redact_prompt`` / ``check_sensitive`` do not touch the redis store,
    but the :class:`Redactor` constructor requires *some* async client.
    Keeping this private avoids leaking an import from fakeredis into
    production code paths that only need the scan-emitting subset.
    """

    async def set(self, *_args, **_kwargs) -> None:
        return None

    async def get(self, *_args, **_kwargs) -> None:
        return None

    async def delete(self, *_args, **_kwargs) -> None:
        return None
