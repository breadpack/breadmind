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
    SCHEDULE = "schedule"     # Calendar/event management (meeting, appointment)
    TASK = "task"             # Task/todo management (todo, reminder, checklist)
    SEARCH_FILES = "search_files"  # File search/document lookup
    CONTACT = "contact"       # Contact/person lookup
    CODING = "coding"         # Software development tasks (implement, refactor, test)


@dataclass
class Intent:
    category: IntentCategory
    confidence: float  # 0.0 ~ 1.0
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)  # IPs, hostnames, service names
    tool_hints: set[str] = field(default_factory=set)   # suggested tools
    urgency: str = "normal"  # "low" | "normal" | "high" | "critical"


# Pattern definitions: (compiled_regex, category, confidence_boost)
_PATTERNS: list[tuple[re.Pattern, IntentCategory, float]] = [
    # DIAGNOSE — problem signals
    (re.compile(r"(오류|에러|error|fail|crash|죽|down|느려|slow|timeout|장애|문제|왜.*안|not\s+work|broken|hung|oom|kill)", re.I), IntentCategory.DIAGNOSE, 0.4),
    (re.compile(r"(로그|log|trace|debug|원인|cause|분석|analyz)", re.I), IntentCategory.DIAGNOSE, 0.3),

    # SCHEDULE — calendar/event management
    (re.compile(r"일정|회의|약속|캘린더|calendar|schedule|meeting|언제.*시간|예약", re.I), IntentCategory.SCHEDULE, 0.7),

    # TASK — todo/task management
    (re.compile(r"할\s*일|해야\s*할|완료|체크|리마인더|마감|todo|task|remind", re.I), IntentCategory.TASK, 0.7),

    # SEARCH_FILES — file/document search
    (re.compile(r"파일|문서|드라이브|drive|document|다운로드|download", re.I), IntentCategory.SEARCH_FILES, 0.6),

    # CONTACT — contact/person lookup
    (re.compile(r"연락처|전화번호|이메일\s*주소|담당자|contact", re.I), IntentCategory.CONTACT, 0.7),

    # CODING — software development tasks
    (re.compile(r"코드|구현|개발|리팩토링|버그\s*수정|테스트\s*작성|프로그래밍|코딩", re.I), IntentCategory.CODING, 0.7),
    (re.compile(r"(?<![a-zA-Z])(code|implement|refactor|fix\s+bug|write\s+test|develop|programming|coding)(?![a-zA-Z])", re.I), IntentCategory.CODING, 0.7),

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
    IntentCategory.SCHEDULE: {"event_create", "event_list", "event_update", "event_delete"},
    IntentCategory.TASK: {"task_create", "task_list", "task_update", "task_delete", "reminder_set"},
    IntentCategory.SEARCH_FILES: {"file_search", "file_read", "file_list"},
    IntentCategory.CONTACT: {"contact_search", "contact_create"},
    IntentCategory.CODING: {"code_delegate"},
}


_URGENCY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"지금\s*당장|즉시|긴급|ASAP|urgent|immediately|right\s*now", re.I), "critical"),
    (re.compile(r"급해|급한|빨리|서둘러|hurry|quick|fast", re.I), "high"),
    (re.compile(r"시간\s*될\s*때|천천히|나중에|여유|when\s*you\s*can|no\s*rush|later", re.I), "low"),
]


def _detect_urgency(message: str) -> str:
    """Detect urgency level from message text."""
    for pattern, urgency in _URGENCY_PATTERNS:
        if pattern.search(message):
            return urgency
    return "normal"


_CATEGORY_PRIORITY: dict[IntentCategory, int] = {
    IntentCategory.SCHEDULE: 0,
    IntentCategory.TASK: 1,
    IntentCategory.CONTACT: 2,
    IntentCategory.SEARCH_FILES: 3,
    IntentCategory.CODING: 4,
    IntentCategory.DIAGNOSE: 5,
    IntentCategory.EXECUTE: 6,
    IntentCategory.CONFIGURE: 7,
    IntentCategory.QUERY: 8,
    IntentCategory.LEARN: 9,
    IntentCategory.CHAT: 10,
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

    # Pick highest-scoring category (priority breaks ties)
    sorted_candidates = sorted(
        scores.items(),
        key=lambda item: (-item[1], _CATEGORY_PRIORITY.get(item[0], 99)),
    )
    best_category = sorted_candidates[0][0]
    best_score = sorted_candidates[0][1]

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

    urgency = _detect_urgency(message)

    return Intent(
        category=best_category,
        confidence=confidence,
        keywords=keywords,
        entities=entities,
        tool_hints=tool_hints,
        urgency=urgency,
    )


# Think budget by intent category (tokens).
# Complex reasoning tasks get more budget, simple ones get less.
# Claude extended_thinking: 1,024 ~ 128,000 / Gemini thinkingBudget: 0 ~ 24,576
_THINK_BUDGETS: dict[IntentCategory, int] = {
    IntentCategory.CHAT: 0,          # Simple conversation — no deep thinking
    IntentCategory.LEARN: 2048,      # Memory ops — minimal reasoning
    IntentCategory.QUERY: 4096,      # Info lookup — data interpretation
    IntentCategory.CONFIGURE: 4096,  # Settings — impact assessment
    IntentCategory.EXECUTE: 10240,   # Actions — multi-step execution planning
    IntentCategory.DIAGNOSE: 16384,  # Troubleshooting — deep root-cause analysis, multiple hypotheses
    IntentCategory.SCHEDULE: 5120,   # Calendar ops — date/time reasoning
    IntentCategory.TASK: 5120,       # Task management — priority assessment
    IntentCategory.SEARCH_FILES: 5120,  # File search — query formulation
    IntentCategory.CONTACT: 3072,    # Contact lookup — simple matching
    IntentCategory.CODING: 12288,    # Coding tasks — planning, design, implementation strategy
}


def get_think_budget(intent: Intent) -> int:
    """Return recommended think budget (tokens) based on intent.

    Higher budget for complex reasoning tasks (diagnose, execute),
    lower or zero for simple tasks (chat, learn).
    """
    return _THINK_BUDGETS.get(intent.category, 2048)


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
