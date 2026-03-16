"""Rule-based intent classifier for user messages.

Classifies messages into intent categories without LLM calls,
enabling intent-aware tool selection and memory retrieval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class IntentCategory(str, Enum):
    QUERY = "query"           # Information lookup (status, logs, metrics)
    EXECUTE = "execute"       # Perform an action (deploy, restart, install)
    DIAGNOSE = "diagnose"     # Troubleshoot a problem (error, slow, crash)
    CONFIGURE = "configure"   # Change settings (config, setup, enable)
    LEARN = "learn"           # Store/retrieve knowledge (remember, forget)
    CHAT = "chat"             # General conversation, greeting


@dataclass
class Intent:
    category: IntentCategory
    confidence: float  # 0.0 ~ 1.0
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)  # IPs, hostnames, service names
    tool_hints: set[str] = field(default_factory=set)   # suggested tools


# Pattern definitions: (compiled_regex, category, confidence_boost)
_PATTERNS: list[tuple[re.Pattern, IntentCategory, float]] = [
    # DIAGNOSE — problem signals
    (re.compile(r"(오류|에러|error|fail|crash|죽|down|느려|slow|timeout|장애|문제|왜.*안|not\s+work|broken|hung|oom|kill)", re.I), IntentCategory.DIAGNOSE, 0.4),
    (re.compile(r"(로그|log|trace|debug|원인|cause|분석|analyz)", re.I), IntentCategory.DIAGNOSE, 0.3),

    # EXECUTE — action verbs
    (re.compile(r"(실행|배포|deploy|restart|재시작|설치|install|삭제|delete|remove|생성|create|시작|start|stop|중지|kill|업데이트|update|upgrade|롤백|rollback|스케일|scale|clean|정리)", re.I), IntentCategory.EXECUTE, 0.4),
    (re.compile(r"(해줘|해\s*주|해봐|하자|해라|해주세요|합시다)", re.I), IntentCategory.EXECUTE, 0.2),

    # QUERY — information requests
    (re.compile(r"(상태|status|확인|check|보여|show|알려|tell|목록|list|어떻게|how|얼마나|조회|뭐|what|info|정보|현재|current|몇|용량|사용량|usage)", re.I), IntentCategory.QUERY, 0.3),
    (re.compile(r"(디스크|disk|메모리|memory|cpu|네트워크|network|포트|port|프로세스|process|pod|node|vm|container|서비스|service)", re.I), IntentCategory.QUERY, 0.2),

    # CONFIGURE — settings changes
    (re.compile(r"(설정|config|세팅|setting|변경|change|수정|modify|바꿔|switch|전환|토글|toggle|활성|enable|비활성|disable|추가|add)", re.I), IntentCategory.CONFIGURE, 0.3),
    (re.compile(r"(api\s*key|모델|model|프로바이더|provider|persona|포트|port|언어|language|테마|theme)", re.I), IntentCategory.CONFIGURE, 0.3),

    # LEARN — memory operations
    (re.compile(r"(기억|remember|잊지|forget|저장|save|메모|memo|학습|learn|외워|기록|record|노트|note)", re.I), IntentCategory.LEARN, 0.5),
    (re.compile(r"(이전에|before|아까|earlier|전에|last\s+time|history|히스토리)", re.I), IntentCategory.LEARN, 0.2),

    # CHAT — greetings and general
    (re.compile(r"^(안녕|hello|hi|hey|반가|감사|고마|thanks|thank|ㅎㅇ|잘\s*부탁)"), IntentCategory.CHAT, 0.5),
]

# Entity extraction patterns
# Use lookaround instead of \b — word boundary fails next to Korean characters
_IP_RE = re.compile(r"(?<![0-9])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![0-9])")
_HOST_RE = re.compile(r"(?<![a-zA-Z0-9-])([a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z][a-zA-Z0-9-]*)+)(?![a-zA-Z0-9-])")
_INFRA_RE = re.compile(
    r"(?<![a-zA-Z0-9._-])((?:pod|svc|deploy|node|vm|container|ns|ingress|pvc|configmap|secret|daemonset|statefulset|job|cronjob)"
    r"[-/][a-zA-Z0-9._-]+)(?![a-zA-Z0-9._-])",
    re.I,
)
_PORT_RE = re.compile(r"(?:port|포트)\s*(\d{2,5})(?![0-9])", re.I)

# Tool hints by category
_TOOL_HINTS: dict[IntentCategory, set[str]] = {
    IntentCategory.QUERY: {"shell_exec", "web_search", "file_read"},
    IntentCategory.EXECUTE: {"shell_exec", "file_write", "browser"},
    IntentCategory.DIAGNOSE: {"shell_exec", "file_read", "web_search"},
    IntentCategory.CONFIGURE: {"file_read", "file_write"},
    IntentCategory.LEARN: {"memory_save", "memory_search"},
    IntentCategory.CHAT: set(),
}


def classify(message: str) -> Intent:
    """Classify a user message into an intent category.

    Uses pattern matching with confidence scoring.
    Falls back to QUERY for ambiguous messages (safer than EXECUTE).
    """
    scores: dict[IntentCategory, float] = {c: 0.0 for c in IntentCategory}

    for pattern, category, boost in _PATTERNS:
        if pattern.search(message):
            scores[category] += boost

    # Pick highest-scoring category
    best_category = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_category]

    # If no pattern matched strongly, default to QUERY (safe fallback)
    if best_score < 0.2:
        best_category = IntentCategory.CHAT if len(message) < 10 else IntentCategory.QUERY
        best_score = 0.3

    # Normalize confidence
    confidence = min(best_score, 1.0)

    # Extract entities
    entities: list[str] = []
    entities.extend(_IP_RE.findall(message))
    entities.extend(_HOST_RE.findall(message))
    entities.extend(_INFRA_RE.findall(message))
    port_matches = _PORT_RE.findall(message)
    if port_matches:
        entities.extend(f"port:{p}" for p in port_matches)

    # Extract keywords (simple: non-stopword tokens)
    keywords = _extract_keywords(message)

    # Tool hints based on category
    tool_hints = set(_TOOL_HINTS.get(best_category, set()))

    # Add entity-specific tool hints
    if any(e for e in entities if _IP_RE.match(e)):
        tool_hints.add("shell_exec")  # likely need to ping/ssh
    if any("pod" in e.lower() or "deploy" in e.lower() for e in entities):
        tool_hints.update({"shell_exec"})  # kubectl commands

    return Intent(
        category=best_category,
        confidence=confidence,
        keywords=keywords,
        entities=entities,
        tool_hints=tool_hints,
    )


_STOPWORDS_KO = frozenset({
    "이", "가", "은", "는", "을", "를", "에", "의", "와", "과", "도", "로",
    "으로", "에서", "까지", "부터", "만", "좀", "것", "수", "등", "및",
    "한", "할", "하는", "된", "되는", "있는", "없는", "그", "저", "이런",
})

_STOPWORDS_EN = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "into", "and", "but", "or", "if", "not", "no",
    "so", "it", "i", "me", "my", "we", "you", "he", "she", "they",
    "this", "that", "what", "which", "who", "how", "just", "very",
})


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9가-힣._-]+", text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        if len(w) < 2 or w in _STOPWORDS_KO or w in _STOPWORDS_EN or w in seen:
            continue
        seen.add(w)
        result.append(w)
    return result
