"""Static catalogue of all searchable settings fields for the SDUI Settings page.

Each entry has:
  label    - Korean human-readable label as shown in the UI
  key      - settings key (matches settings_write action key)
  tab      - internal tab ID (one of the _TAB_INDEX keys in settings_view)
  field_id - SDUI component id (used by the frontend for scroll-to)
"""
from __future__ import annotations

SETTINGS_CATALOGUE: list[dict] = [
    # ── Quick Start: LLM ─────────────────────────────────────────────────────
    {"label": "프로바이더", "key": "llm", "tab": "quick_start", "field_id": "qs-llm-provider"},
    {"label": "기본 모델", "key": "llm", "tab": "quick_start", "field_id": "qs-llm-model"},
    {"label": "도구 호출 최대 턴", "key": "llm", "tab": "quick_start", "field_id": "qs-llm-turns"},
    # ── Quick Start: API Keys ─────────────────────────────────────────────────
    {"label": "Anthropic (Claude) API 키", "key": "apikey:ANTHROPIC_API_KEY", "tab": "quick_start", "field_id": "qs-apikey-field-ANTHROPIC_API_KEY"},
    {"label": "Google (Gemini) API 키", "key": "apikey:GEMINI_API_KEY", "tab": "quick_start", "field_id": "qs-apikey-field-GEMINI_API_KEY"},
    {"label": "OpenAI API 키", "key": "apikey:OPENAI_API_KEY", "tab": "quick_start", "field_id": "qs-apikey-field-OPENAI_API_KEY"},
    {"label": "xAI (Grok) API 키", "key": "apikey:XAI_API_KEY", "tab": "quick_start", "field_id": "qs-apikey-field-XAI_API_KEY"},
    # ── Quick Start: Persona ──────────────────────────────────────────────────
    {"label": "이름", "key": "persona", "tab": "quick_start", "field_id": "qs-persona-name"},
    {"label": "프리셋", "key": "persona", "tab": "quick_start", "field_id": "qs-persona-preset"},
    {"label": "언어", "key": "persona", "tab": "quick_start", "field_id": "qs-persona-lang"},
    # ── Agent Behavior: Prompts ───────────────────────────────────────────────
    {"label": "메인 시스템 프롬프트", "key": "custom_prompts", "tab": "agent_behavior", "field_id": "ab-prompts-main"},
    {"label": "행동 가이드", "key": "custom_prompts", "tab": "agent_behavior", "field_id": "ab-prompts-behavior"},
    # ── Agent Behavior: Instructions ──────────────────────────────────────────
    {"label": "지시사항", "key": "custom_instructions", "tab": "agent_behavior", "field_id": "ab-inst-field"},
    # ── Agent Behavior: Embedding ─────────────────────────────────────────────
    {"label": "임베딩 프로바이더", "key": "embedding_config", "tab": "agent_behavior", "field_id": "ab-emb-provider"},
    {"label": "임베딩 모델 이름", "key": "embedding_config", "tab": "agent_behavior", "field_id": "ab-emb-model"},
    # ── Integrations: MCP Global ──────────────────────────────────────────────
    {"label": "MCP 자동 검색", "key": "mcp", "tab": "integrations", "field_id": "int-mcp-auto-discover"},
    {"label": "MCP 최대 재시작 횟수", "key": "mcp", "tab": "integrations", "field_id": "int-mcp-max-restart"},
    # ── Integrations: MCP Servers ─────────────────────────────────────────────
    {"label": "MCP 서버 목록", "key": "mcp_servers", "tab": "integrations", "field_id": "int-mcp-servers"},
    # ── Integrations: Skill Markets ───────────────────────────────────────────
    {"label": "스킬 마켓 목록", "key": "skill_markets", "tab": "integrations", "field_id": "int-skill-markets"},
    # ── Safety: Blacklist ─────────────────────────────────────────────────────
    {"label": "차단 도구 목록", "key": "safety_blacklist", "tab": "safety", "field_id": "safety-blacklist"},
    # ── Safety: Approval ─────────────────────────────────────────────────────
    {"label": "승인 필요 도구 목록", "key": "safety_approval", "tab": "safety", "field_id": "safety-approval"},
    # ── Safety: Permissions ───────────────────────────────────────────────────
    {"label": "사용자 권한", "key": "safety_permissions", "tab": "safety", "field_id": "safety-permissions"},
    # ── Safety: Tool Security ─────────────────────────────────────────────────
    {"label": "기본 디렉토리", "key": "tool_security", "tab": "safety", "field_id": "safety-tool-sec-basedir"},
    {"label": "커맨드 화이트리스트 활성화", "key": "tool_security", "tab": "safety", "field_id": "safety-tool-sec-whitelist-enabled"},
    # ── Monitoring: Rules ─────────────────────────────────────────────────────
    {"label": "모니터링 규칙 목록", "key": "monitoring_config", "tab": "monitoring", "field_id": "mon-rules"},
    # ── Monitoring: Loop Protector ────────────────────────────────────────────
    {"label": "쿨다운 (분)", "key": "monitoring_config", "tab": "monitoring", "field_id": "mon-loop-cooldown"},
    {"label": "최대 자동 작업 수", "key": "monitoring_config", "tab": "monitoring", "field_id": "mon-loop-max-actions"},
    # ── Monitoring: Scheduler Cron ────────────────────────────────────────────
    {"label": "스케줄러 크론 목록", "key": "scheduler_cron", "tab": "monitoring", "field_id": "mon-scheduler-cron"},
    # ── Memory: GC Config ─────────────────────────────────────────────────────
    {"label": "GC 주기 (초)", "key": "memory_gc_config", "tab": "memory", "field_id": "mem-gc-interval"},
    {"label": "감쇠 임계값", "key": "memory_gc_config", "tab": "memory", "field_id": "mem-gc-decay"},
    {"label": "최대 캐시 노트 수", "key": "memory_gc_config", "tab": "memory", "field_id": "mem-gc-notes"},
    {"label": "지식 그래프 최대 보존 기간 (일)", "key": "memory_gc_config", "tab": "memory", "field_id": "mem-gc-age"},
    {"label": "환경 갱신 주기 (초)", "key": "memory_gc_config", "tab": "memory", "field_id": "mem-gc-env-refresh"},
    # ── Advanced: System Timeouts ─────────────────────────────────────────────
    {"label": "도구 호출 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-tool_call"},
    {"label": "LLM API 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-llm_api"},
    {"label": "SSH 명령 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-ssh_command"},
    {"label": "헬스 체크 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-health_check"},
    {"label": "PyPI 확인 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-pypi_check"},
    {"label": "HTTP 기본 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-http_default"},
    {"label": "스킬 탐색 타임아웃 (초)", "key": "system_timeouts", "tab": "advanced", "field_id": "adv-st-skill_discovery"},
    # ── Advanced: Retry Config ────────────────────────────────────────────────
    {"label": "최대 재시도 횟수", "key": "retry_config", "tab": "advanced", "field_id": "adv-retry-max_retries"},
    {"label": "LLM 최대 재시도 횟수", "key": "retry_config", "tab": "advanced", "field_id": "adv-retry-llm_max_retries"},
    {"label": "게이트웨이 최대 재시도 횟수", "key": "retry_config", "tab": "advanced", "field_id": "adv-retry-gateway_max_retries"},
    {"label": "기본 백오프 (초)", "key": "retry_config", "tab": "advanced", "field_id": "adv-retry-base_backoff"},
    {"label": "최대 백오프 (초)", "key": "retry_config", "tab": "advanced", "field_id": "adv-retry-max_backoff"},
    {"label": "헬스 체크 간격 (초)", "key": "retry_config", "tab": "advanced", "field_id": "adv-retry-health_check_interval"},
    # ── Advanced: Limits Config ───────────────────────────────────────────────
    {"label": "최대 도구 수", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-max_tools"},
    {"label": "최대 컨텍스트 토큰", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-max_context_tokens"},
    {"label": "도메인별 최대 스킬 수", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-max_per_domain_skills"},
    {"label": "감사 로그 보존 수", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-audit_log_recent"},
    {"label": "임베딩 캐시 크기", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-embedding_cache_size"},
    {"label": "상위 역할 제한", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-top_roles_limit"},
    {"label": "스마트 검색 토큰 예산", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-smart_retriever_token_budget"},
    {"label": "스마트 검색 결과 제한", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-smart_retriever_limit"},
    {"label": "저성능 임계값", "key": "limits_config", "tab": "advanced", "field_id": "adv-limits-low-perf"},
    # ── Advanced: Polling Config ──────────────────────────────────────────────
    {"label": "Signal 폴링 간격 (초)", "key": "polling_config", "tab": "advanced", "field_id": "adv-polling-signal_interval"},
    {"label": "Gmail 폴링 간격 (초)", "key": "polling_config", "tab": "advanced", "field_id": "adv-polling-gmail_interval"},
    {"label": "업데이트 확인 간격 (초)", "key": "polling_config", "tab": "advanced", "field_id": "adv-polling-update_check_interval"},
    {"label": "데이터 플러시 간격 (초)", "key": "polling_config", "tab": "advanced", "field_id": "adv-polling-data_flush_interval"},
    {"label": "자동 정리 간격 (초)", "key": "polling_config", "tab": "advanced", "field_id": "adv-polling-auto_cleanup_interval"},
    # ── Advanced: Agent Timeouts ──────────────────────────────────────────────
    {"label": "에이전트 도구 타임아웃 (초)", "key": "agent_timeouts", "tab": "advanced", "field_id": "adv-at-tool_timeout"},
    {"label": "에이전트 채팅 타임아웃 (초)", "key": "agent_timeouts", "tab": "advanced", "field_id": "adv-at-chat_timeout"},
    {"label": "에이전트 최대 턴 수", "key": "agent_timeouts", "tab": "advanced", "field_id": "adv-at-max_turns"},
    # ── Advanced: Logging ─────────────────────────────────────────────────────
    {"label": "로그 레벨", "key": "logging_config", "tab": "advanced", "field_id": "adv-log-level"},
    {"label": "로그 형식", "key": "logging_config", "tab": "advanced", "field_id": "adv-log-format"},
    # ── Advanced: Vault & Audit ───────────────────────────────────────────────
    {"label": "자격증명 금고", "key": "vault", "tab": "advanced", "field_id": "adv-vault"},
    {"label": "설정 변경 이력", "key": "sdui_audit_log", "tab": "advanced", "field_id": "adv-audit"},
]

_VALID_TABS = {
    "quick_start",
    "agent_behavior",
    "integrations",
    "safety",
    "monitoring",
    "memory",
    "advanced",
}


def search_settings(query: str) -> list[dict]:
    """Search the settings catalogue by label or key substring (case-insensitive).

    Args:
        query: search string.

    Returns:
        Up to 20 matching catalogue entries. Empty list when query is empty/None.
    """
    if not query:
        return []
    q = query.lower()
    results: list[dict] = []
    for entry in SETTINGS_CATALOGUE:
        if q in entry["label"].lower() or q in entry["key"].lower():
            results.append(entry)
        if len(results) >= 20:
            break
    return results
