from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from enum import Enum

# Korean stopwords (compact set; expand cautiously)
_KO_STOPWORDS = frozenset({
    "을", "를", "이", "가", "은", "는", "의", "에", "에서", "와", "과", "도",
    "로", "으로", "께", "에게", "한테", "부터", "까지", "고", "며", "면",
    "이다", "있다", "없다", "그리고", "그러나", "하지만", "또는", "혹은",
    "그", "이", "저", "것", "수", "등", "및",
})

_EN_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "as", "into", "and", "or", "if", "that",
    "this", "it", "i", "me", "my", "we", "our", "you", "your", "he", "she",
    "they", "them", "their", "what", "which", "who", "whom", "its", "about",
})

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_.]*|[가-힣]+")
_MAX_KEYWORDS = 12


class SignalKind(str, Enum):
    TOOL_EXECUTED = "tool_executed"
    TOOL_FAILED = "tool_failed"
    REFLEXION = "reflexion"
    USER_CORRECTION = "user_correction"
    EXPLICIT_PIN = "explicit_pin"
    NEUTRAL = "neutral"  # used when storing legacy notes / fallback


@dataclass(frozen=True)
class SignalEvent:
    kind: SignalKind
    user_id: str
    session_id: uuid.UUID | None
    org_id: uuid.UUID | None = None
    user_message: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result_text: str | None = None
    prior_turn_summary: str | None = None


def stable_hash(args: dict | None) -> str | None:
    if not args:
        return None
    blob = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def keyword_extract(text_or_args: str | dict) -> list[str]:
    if isinstance(text_or_args, dict):
        text = " ".join(str(v) for v in text_or_args.values())
    else:
        text = text_or_args or ""
    out: list[str] = []
    seen: set[str] = set()
    for m in _TOKEN_RE.findall(text.lower()):
        if m in _EN_STOPWORDS or m in _KO_STOPWORDS:
            continue
        if len(m) < 2:
            continue
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
        if len(out) >= _MAX_KEYWORDS:
            break
    return out
