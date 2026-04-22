"""Single choke-point for scrubbing secrets from any smoke output.

Regex set mirrors ``tests/kb/connectors/conftest.py::_SECRET_BODY_PATTERNS``
(P5 VCR scrubber). Operates on ``str`` (smoke formats strings, not raw
response bytes). Every string destined for stdout/stderr/log MUST pass
through ``redact_secrets`` before rendering.
"""
from __future__ import annotations

import re

_MAX_DETAIL_CHARS = 400

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
     "scrubbed@example.com"),
    (re.compile(r"ATATT[A-Za-z0-9+/=_-]{20,}"), "ATATT_REDACTED"),
    (re.compile(r'"(access_token|refresh_token|api_token|apikey|api_key|secret)"\s*:\s*"[^"]+"'),
     r'"\1": "REDACTED"'),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA_REDACTED"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "xoxb-REDACTED"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"), "sk-ant-REDACTED"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"), "Bearer REDACTED"),
)


def redact_secrets(s: str) -> str:
    """Apply every scrubber pattern then truncate to 400 chars."""
    out = s
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    if len(out) > _MAX_DETAIL_CHARS:
        out = out[: _MAX_DETAIL_CHARS - 1] + "…"
    return out
