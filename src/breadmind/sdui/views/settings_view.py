"""Settings view: Phase 1 + Phase 2 editable settings, Phase 3 placeholder tabs.

Phase 1 (editable):
  - Quick Start: LLM provider, API keys, persona
  - Agent Behavior: prompts, instructions, embedding backend

Phase 2 (editable):
  - Integrations: MCP global config, MCP server list, skill markets
  - Safety & Permissions: blacklist, approval list, user permissions, tool security
  - Monitoring: monitoring rules, loop protector, scheduler cron

Phase 3 (placeholder):
  - Memory, Advanced

All forms emit ``settings_write`` actions; the action handler validates and
persists via the settings store or credential vault.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from breadmind.sdui.settings_schema import mask_credential
from breadmind.sdui.spec import Component, UISpec

logger = logging.getLogger(__name__)

_API_KEYS = [
    ("ANTHROPIC_API_KEY", "Anthropic (Claude)"),
    ("GEMINI_API_KEY", "Google (Gemini)"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("XAI_API_KEY", "xAI (Grok)"),
]

_PERSONA_PRESET_OPTIONS = [
    {"value": "professional", "label": "전문적"},
    {"value": "friendly", "label": "친근함"},
    {"value": "concise", "label": "간결함"},
    {"value": "humorous", "label": "유머러스"},
]

_PROVIDER_OPTIONS = [
    {"value": "gemini", "label": "Gemini"},
    {"value": "claude", "label": "Claude"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "grok", "label": "Grok"},
    {"value": "ollama", "label": "Ollama (local)"},
]

_EMBEDDING_PROVIDER_OPTIONS = [
    {"value": "auto", "label": "자동"},
    {"value": "fastembed", "label": "FastEmbed"},
    {"value": "ollama", "label": "Ollama"},
    {"value": "local", "label": "Local"},
    {"value": "gemini", "label": "Gemini"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "off", "label": "비활성화"},
]

_SKILL_MARKET_TYPE_OPTIONS = [
    {"value": "skills_sh", "label": "skills.sh"},
    {"value": "skillsmp", "label": "SkillsMCP"},
    {"value": "clawhub", "label": "ClawHub"},
    {"value": "mcp_registry", "label": "MCP Registry"},
]

_BOOL_OPTIONS = [
    {"value": "true", "label": "활성화"},
    {"value": "false", "label": "비활성화"},
]

# ── Phase 3 defaults ───────────────────────────────────────────────────────

_MEMORY_GC_DEFAULTS: dict[str, Any] = {
    "interval_seconds": 3600,
    "decay_threshold": 0.1,
    "max_cached_notes": 500,
    "kg_max_age_days": 90,
    "env_refresh_interval": 6,
}

_SYSTEM_TIMEOUTS_DEFAULTS: dict[str, Any] = {
    "tool_call": 60,
    "llm_api": 120,
    "ssh_command": 60,
    "health_check": 10,
    "pypi_check": 30,
    "http_default": 30,
    "skill_discovery": 60,
}

_RETRY_CONFIG_DEFAULTS: dict[str, Any] = {
    "max_retries": 3,
    "llm_max_retries": 3,
    "gateway_max_retries": 3,
    "base_backoff": 5,
    "max_backoff": 60,
    "health_check_interval": 30,
}

_LIMITS_CONFIG_DEFAULTS: dict[str, Any] = {
    "max_tools": 50,
    "max_context_tokens": 100000,
    "max_per_domain_skills": 10,
    "audit_log_recent": 100,
    "embedding_cache_size": 1000,
    "top_roles_limit": 10,
    "smart_retriever_token_budget": 4000,
    "smart_retriever_limit": 10,
    "low_performance_threshold": 0.5,
}

_POLLING_CONFIG_DEFAULTS: dict[str, Any] = {
    "signal_interval": 60,
    "gmail_interval": 300,
    "update_check_interval": 86400,
    "data_flush_interval": 60,
    "auto_cleanup_interval": 3600,
}

_AGENT_TIMEOUTS_DEFAULTS: dict[str, Any] = {
    "tool_timeout": 60,
    "chat_timeout": 300,
    "max_turns": 20,
}

_LOGGING_CONFIG_DEFAULTS: dict[str, Any] = {
    "level": "INFO",
    "format": "text",
}

_LOG_LEVEL_OPTIONS = [
    {"value": "DEBUG", "label": "DEBUG"},
    {"value": "INFO", "label": "INFO"},
    {"value": "WARNING", "label": "WARNING"},
    {"value": "ERROR", "label": "ERROR"},
    {"value": "CRITICAL", "label": "CRITICAL"},
]

_LOG_FORMAT_OPTIONS = [
    {"value": "json", "label": "JSON"},
    {"value": "text", "label": "텍스트"},
]


async def build(
    db: Any,
    *,
    settings_store: Any = None,
    user_id: str | None = None,
    **_kwargs: Any,
) -> UISpec:
    # Phase 1 data
    llm = await _safe_get(settings_store, "llm", {}) or {}
    persona = await _safe_get(settings_store, "persona", {}) or {}
    prompts = await _safe_get(settings_store, "custom_prompts", {}) or {}
    instructions = await _safe_get(settings_store, "custom_instructions", "") or ""
    embedding = await _safe_get(settings_store, "embedding_config", {}) or {}
    apikey_status = {}
    for name, _ in _API_KEYS:
        apikey_status[name] = await _safe_get(settings_store, f"apikey:{name}", None)

    # Phase 2 data
    mcp_config = await _safe_get(settings_store, "mcp", {}) or {}
    mcp_servers = await _safe_get(settings_store, "mcp_servers", []) or []
    skill_markets = await _safe_get(settings_store, "skill_markets", []) or []
    safety_blacklist = await _safe_get(settings_store, "safety_blacklist", {}) or {}
    safety_approval = await _safe_get(settings_store, "safety_approval", []) or []
    safety_permissions = await _safe_get(settings_store, "safety_permissions", {}) or {}
    tool_security = await _safe_get(settings_store, "tool_security", {}) or {}
    monitoring_config = await _safe_get(settings_store, "monitoring_config", {}) or {}
    scheduler_cron = await _safe_get(settings_store, "scheduler_cron", []) or []

    # Phase 3 data
    memory_gc_config = await _safe_get(settings_store, "memory_gc_config", {}) or {}
    system_timeouts = await _safe_get(settings_store, "system_timeouts", {}) or {}
    retry_config = await _safe_get(settings_store, "retry_config", {}) or {}
    limits_config = await _safe_get(settings_store, "limits_config", {}) or {}
    polling_config = await _safe_get(settings_store, "polling_config", {}) or {}
    agent_timeouts = await _safe_get(settings_store, "agent_timeouts", {}) or {}
    logging_config = await _safe_get(settings_store, "logging_config", {}) or {}
    vault_entries = await _safe_list_vault_entries(db)

    # Phase 4: admin gating — 안전 & 권한 and 고급 tabs are admin-only.
    # If admin_users is empty/missing, NOBODY is admin (closed by default).
    admin_users: list = (
        safety_permissions.get("admin_users") or []
        if isinstance(safety_permissions, dict)
        else []
    )
    is_admin: bool = bool(user_id and user_id in admin_users)

    # Build tabs list, filtering out admin-only tabs for non-admins.
    tabs: list[Component] = [
        _quick_start_tab(llm, persona, apikey_status),
        _agent_behavior_tab(prompts, instructions, embedding),
        _integrations_tab(mcp_config, mcp_servers, skill_markets),
    ]
    if is_admin:
        tabs.append(_safety_tab(safety_blacklist, safety_approval, safety_permissions, tool_security))
    tabs.append(_monitoring_tab(monitoring_config, scheduler_cron))
    tabs.append(_memory_tab(memory_gc_config))
    if is_admin:
        tabs.append(
            _advanced_tab(
                system_timeouts,
                retry_config,
                limits_config,
                polling_config,
                agent_timeouts,
                logging_config,
                vault_entries,
            )
        )

    # Show a hint for non-admin users so the first operator knows to set admin_users.
    page_children: list[Component] = [
        Component(type="heading", id="settings-h", props={"value": "설정", "level": 2}),
        Component(type="tabs", id="settings-tabs", props={}, children=tabs),
    ]
    if not is_admin:
        page_children.append(
            Component(
                type="text",
                id="settings-admin-hint",
                props={
                    "value": "안전 & 권한, 고급 탭은 관리자만 접근할 수 있습니다.",
                    "variant": "muted",
                },
            )
        )

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="settings",
            props={"title": "설정"},
            children=page_children,
        ),
    )


async def _safe_get(store: Any, key: str, default: Any) -> Any:
    if store is None:
        return default
    try:
        getter = getattr(store, "get_setting", None)
        if getter is None:
            return default
        value = await getter(key)
        return default if value is None else value
    except Exception as exc:  # noqa: BLE001
        logger.debug("settings_view: get_setting(%s) failed: %s", key, exc)
        return default


async def _safe_list_prefix(store: Any, prefix: str) -> list[str]:
    """Return keys from store matching prefix; returns [] on any failure."""
    if store is None:
        return []
    try:
        lister = getattr(store, "list_settings_by_prefix", None)
        if lister is None:
            return []
        result = await lister(prefix)
        return result if isinstance(result, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("settings_view: list_settings_by_prefix(%s) failed: %s", prefix, exc)
        return []


async def _safe_list_vault_entries(db: Any) -> list[dict] | None:
    """Return a list of vault entry dicts (id, stored_at, has_metadata), or None.

    Returns:
      None   — db has no list_settings_by_prefix (vault unavailable)
      []     — method exists but no vault keys found (vault empty)
      [...]  — one dict per vault entry, up to 100

    Each dict: {"id": str, "stored_at": float | None, "has_metadata": bool}
    """
    if db is None:
        return None
    try:
        lister = getattr(db, "list_settings_by_prefix", None)
        if lister is None:
            return None
        keys = await lister("vault:")
        if not isinstance(keys, list):
            return []
        entries: list[dict] = []
        for key in keys[:100]:
            try:
                data = await db.get_setting(key)
                if not isinstance(data, dict):
                    data = {}
                entries.append(
                    {
                        "id": key.removeprefix("vault:"),
                        "stored_at": data.get("stored_at"),
                        "has_metadata": bool(data.get("metadata")),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("settings_view: get_setting(%s) failed: %s", key, exc)
        return entries
    except Exception as exc:  # noqa: BLE001
        logger.debug("settings_view: _safe_list_vault_entries failed: %s", exc)
        return None


def _format_timestamp(ts: float | None) -> str:
    """Convert a Unix timestamp to 'YYYY-MM-DD HH:MM' string, or '-' if None."""
    if ts is None:
        return "-"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return "-"


# ── Tab: Quick Start ───────────────────────────────────────────────────────

def _quick_start_tab(llm: dict, persona: dict, apikey_status: dict) -> Component:
    return Component(
        type="stack",
        id="tab-quick-start",
        props={"label": "빠른 시작", "gap": "md"},
        children=[
            Component(type="heading", id="qs-h", props={"value": "빠른 시작", "level": 3}),
            _llm_card(llm),
            _apikey_card(apikey_status),
            _persona_card(persona),
        ],
    )


def _llm_card(llm: dict) -> Component:
    provider = llm.get("default_provider", "gemini") if isinstance(llm, dict) else "gemini"
    model = llm.get("default_model", "") if isinstance(llm, dict) else ""
    max_turns = llm.get("tool_call_max_turns", 10) if isinstance(llm, dict) else 10
    return Component(
        type="list",
        id="qs-llm",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="qs-llm-h", props={"value": "LLM 프로바이더", "level": 4}),
            Component(type="text", id="qs-llm-d", props={"value": "기본 모델과 도구 호출 제한을 설정합니다."}),
            Component(
                type="form",
                id="qs-llm-form",
                props={
                    "action": {"kind": "settings_write", "key": "llm"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="select",
                        id="qs-llm-provider",
                        props={
                            "name": "default_provider",
                            "label": "프로바이더",
                            "value": provider,
                            "options": _PROVIDER_OPTIONS,
                        },
                    ),
                    Component(
                        type="field",
                        id="qs-llm-model",
                        props={
                            "name": "default_model",
                            "label": "기본 모델",
                            "value": str(model),
                            "type": "text",
                        },
                    ),
                    Component(
                        type="field",
                        id="qs-llm-turns",
                        props={
                            "name": "tool_call_max_turns",
                            "label": "도구 호출 최대 턴",
                            "value": str(max_turns),
                            "type": "number",
                        },
                    ),
                ],
            ),
        ],
    )


def _apikey_card(status: dict) -> Component:
    kv_items = [
        {"key": f"{name} ({label})", "value": _mask_status(status.get(name))}
        for name, label in _API_KEYS
    ]
    forms: list[Component] = []
    for name, label in _API_KEYS:
        forms.append(
            Component(
                type="form",
                id=f"qs-apikey-form-{name}",
                props={
                    "action": {"kind": "settings_write", "key": f"apikey:{name}"},
                    "submit_label": f"{label} 저장",
                },
                children=[
                    Component(
                        type="field",
                        id=f"qs-apikey-field-{name}",
                        props={
                            "name": "value",
                            "label": label,
                            "value": "",
                            "type": "password",
                        },
                    ),
                ],
            )
        )
    return Component(
        type="list",
        id="qs-apikey",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="qs-apikey-h", props={"value": "API 키", "level": 4}),
            Component(type="text", id="qs-apikey-d", props={"value": "각 프로바이더의 API 키를 입력하세요. 저장 후 마스킹 표시됩니다."}),
            Component(type="kv", id="qs-apikey-status", props={"items": kv_items}),
            *forms,
        ],
    )


def _mask_status(value: Any) -> str:
    if value is None:
        return "미설정"
    if isinstance(value, dict):
        # vault stores {"encrypted": ..., "stored_at": ...}
        return "●●●● (저장됨)"
    return mask_credential(str(value))


def _persona_card(persona: dict) -> Component:
    name = persona.get("name", "") if isinstance(persona, dict) else ""
    preset = persona.get("preset", "professional") if isinstance(persona, dict) else "professional"
    language = persona.get("language", "ko") if isinstance(persona, dict) else "ko"
    return Component(
        type="list",
        id="qs-persona",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="qs-persona-h", props={"value": "페르소나", "level": 4}),
            Component(type="text", id="qs-persona-d", props={"value": "에이전트의 말투와 스타일을 설정합니다."}),
            Component(
                type="form",
                id="qs-persona-form",
                props={
                    "action": {"kind": "settings_write", "key": "persona"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id="qs-persona-name",
                        props={
                            "name": "name",
                            "label": "이름",
                            "value": str(name),
                            "type": "text",
                        },
                    ),
                    Component(
                        type="select",
                        id="qs-persona-preset",
                        props={
                            "name": "preset",
                            "label": "프리셋",
                            "value": preset,
                            "options": _PERSONA_PRESET_OPTIONS,
                        },
                    ),
                    Component(
                        type="field",
                        id="qs-persona-lang",
                        props={
                            "name": "language",
                            "label": "언어",
                            "value": str(language),
                            "type": "text",
                        },
                    ),
                ],
            ),
        ],
    )


# ── Tab: Agent Behavior ────────────────────────────────────────────────────

def _agent_behavior_tab(prompts: dict, instructions: str, embedding: dict) -> Component:
    return Component(
        type="stack",
        id="tab-agent",
        props={"label": "에이전트 동작", "gap": "md"},
        children=[
            Component(type="heading", id="ab-h", props={"value": "에이전트 동작", "level": 3}),
            _prompts_card(prompts),
            _instructions_card(instructions),
            _embedding_card(embedding),
        ],
    )


def _prompts_card(prompts: dict) -> Component:
    main = prompts.get("main_system_prompt", "") if isinstance(prompts, dict) else ""
    behavior = prompts.get("behavior_prompt", "") if isinstance(prompts, dict) else ""
    return Component(
        type="list",
        id="ab-prompts",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="ab-prompts-h", props={"value": "시스템 프롬프트", "level": 4}),
            Component(type="text", id="ab-prompts-d", props={"value": "에이전트의 핵심 지시사항입니다. 빈 값으로 저장하면 기본 프롬프트가 사용됩니다."}),
            Component(
                type="form",
                id="ab-prompts-form",
                props={
                    "action": {"kind": "settings_write", "key": "custom_prompts"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id="ab-prompts-main",
                        props={
                            "name": "main_system_prompt",
                            "label": "메인 시스템 프롬프트",
                            "value": str(main),
                            "type": "text",
                            "multiline": True,
                        },
                    ),
                    Component(
                        type="field",
                        id="ab-prompts-behavior",
                        props={
                            "name": "behavior_prompt",
                            "label": "행동 가이드",
                            "value": str(behavior),
                            "type": "text",
                            "multiline": True,
                        },
                    ),
                ],
            ),
        ],
    )


def _instructions_card(instructions: str) -> Component:
    return Component(
        type="list",
        id="ab-inst",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="ab-inst-h", props={"value": "사용자 지시사항", "level": 4}),
            Component(type="text", id="ab-inst-d", props={"value": "에이전트가 항상 따라야 할 개인적인 지시사항을 입력하세요. (최대 8000자)"}),
            Component(
                type="form",
                id="ab-inst-form",
                props={
                    "action": {"kind": "settings_write", "key": "custom_instructions"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id="ab-inst-field",
                        props={
                            "name": "value",
                            "label": "지시사항",
                            "value": str(instructions),
                            "type": "text",
                            "multiline": True,
                        },
                    ),
                ],
            ),
        ],
    )


def _embedding_card(embedding: dict) -> Component:
    provider = embedding.get("provider", "auto") if isinstance(embedding, dict) else "auto"
    model = embedding.get("model_name", "") if isinstance(embedding, dict) else ""
    return Component(
        type="list",
        id="ab-emb",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="ab-emb-h", props={"value": "임베딩 백엔드", "level": 4}),
            Component(type="text", id="ab-emb-warn", props={"value": "⚠️ 임베딩 변경 시 재시작이 필요합니다."}),
            Component(
                type="form",
                id="ab-emb-form",
                props={
                    "action": {"kind": "settings_write", "key": "embedding_config"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="select",
                        id="ab-emb-provider",
                        props={
                            "name": "provider",
                            "label": "프로바이더",
                            "value": provider,
                            "options": _EMBEDDING_PROVIDER_OPTIONS,
                        },
                    ),
                    Component(
                        type="field",
                        id="ab-emb-model",
                        props={
                            "name": "model_name",
                            "label": "모델 이름 (선택)",
                            "value": str(model) if model else "",
                            "type": "text",
                        },
                    ),
                ],
            ),
        ],
    )


# ── Helper: chip-style item with delete button ────────────────────────────

def _chip_with_delete(chip_id: str, label: str, delete_action: dict) -> Component:
    """A small inline stack: label text + delete button, used for chip lists."""
    return Component(
        type="stack",
        id=chip_id,
        props={"direction": "horizontal", "gap": "xs", "align": "center"},
        children=[
            Component(
                type="badge",
                id=f"{chip_id}-label",
                props={"value": label},
            ),
            Component(
                type="button",
                id=f"{chip_id}-del",
                props={"label": "삭제", "variant": "danger-sm", "action": delete_action},
            ),
        ],
    )


# ── Tab: Integrations ─────────────────────────────────────────────────────

def _integrations_tab(
    mcp_config: dict,
    mcp_servers: list,
    skill_markets: list,
) -> Component:
    return Component(
        type="stack",
        id="tab-integrations",
        props={"label": "통합", "gap": "md"},
        children=[
            Component(type="heading", id="int-h", props={"value": "통합", "level": 3}),
            _mcp_global_card(mcp_config),
            _mcp_servers_card(mcp_servers),
            _skill_markets_card(skill_markets),
        ],
    )


def _mcp_global_card(mcp_config: dict) -> Component:
    auto_discover = mcp_config.get("auto_discover", True) if isinstance(mcp_config, dict) else True
    max_restart = mcp_config.get("max_restart_attempts", 3) if isinstance(mcp_config, dict) else 3
    return Component(
        type="list",
        id="int-mcp-global",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="int-mcp-global-h", props={"value": "MCP 글로벌 설정", "level": 4}),
            Component(type="text", id="int-mcp-global-d", props={"value": "MCP 서버 자동 검색 및 재시작 정책을 설정합니다."}),
            Component(
                type="form",
                id="int-mcp-global-form",
                props={
                    "action": {"kind": "settings_write", "key": "mcp"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="select",
                        id="int-mcp-auto-discover",
                        props={
                            "name": "auto_discover",
                            "label": "자동 검색",
                            "value": str(auto_discover).lower(),
                            "options": [
                                {"value": "true", "label": "활성화"},
                                {"value": "false", "label": "비활성화"},
                            ],
                        },
                    ),
                    Component(
                        type="field",
                        id="int-mcp-max-restart",
                        props={
                            "name": "max_restart_attempts",
                            "label": "최대 재시작 횟수",
                            "value": str(max_restart),
                            "type": "number",
                        },
                    ),
                ],
            ),
        ],
    )


def _mcp_servers_card(mcp_servers: list) -> Component:
    server_children: list[Component] = [
        Component(type="heading", id="int-mcp-srv-h", props={"value": "MCP 서버 목록", "level": 4}),
        Component(type="text", id="int-mcp-srv-d", props={"value": "등록된 MCP 서버 목록입니다."}),
    ]
    if not mcp_servers:
        server_children.append(
            Component(type="text", id="int-mcp-srv-empty", props={"value": "등록된 MCP 서버가 없습니다."})
        )
    else:
        for idx, srv in enumerate(mcp_servers):
            name = srv.get("name", f"server-{idx}")
            remaining = [s for s in mcp_servers if s.get("name") != name]
            args_str = ", ".join(srv.get("args", []))
            enabled_str = "활성" if srv.get("enabled", True) else "비활성"
            server_children.append(
                Component(
                    type="list",
                    id=f"int-mcp-srv-{idx}",
                    props={"variant": "sub-card"},
                    children=[
                        Component(type="heading", id=f"int-mcp-srv-{idx}-h", props={"value": name, "level": 5}),
                        Component(
                            type="kv",
                            id=f"int-mcp-srv-{idx}-kv",
                            props={
                                "items": [
                                    {"key": "command", "value": srv.get("command", "")},
                                    {"key": "args", "value": args_str},
                                    {"key": "enabled", "value": enabled_str},
                                ]
                            },
                        ),
                        Component(
                            type="button",
                            id=f"int-mcp-srv-{idx}-del",
                            props={
                                "label": "삭제",
                                "variant": "danger-sm",
                                "action": {
                                    "kind": "settings_write",
                                    "key": "mcp_servers",
                                    "values": remaining,
                                },
                            },
                        ),
                    ],
                )
            )
    server_children.append(
        Component(
            type="form",
            id="int-mcp-add-form",
            props={
                "action": {"kind": "settings_append", "key": "mcp_servers"},
                "submit_label": "+ 추가",
            },
            children=[
                Component(
                    type="field",
                    id="int-mcp-add-name",
                    props={"name": "name", "label": "이름", "value": "", "type": "text"},
                ),
                Component(
                    type="field",
                    id="int-mcp-add-command",
                    props={"name": "command", "label": "명령어", "value": "", "type": "text"},
                ),
            ],
        )
    )
    return Component(
        type="list",
        id="int-mcp-servers",
        props={"variant": "settings-card"},
        children=server_children,
    )


def _skill_markets_card(skill_markets: list) -> Component:
    children: list[Component] = [
        Component(type="heading", id="int-skill-h", props={"value": "스킬 마켓", "level": 4}),
        Component(type="text", id="int-skill-d", props={"value": "연결된 스킬 마켓 목록입니다."}),
    ]
    if not skill_markets:
        children.append(
            Component(type="text", id="int-skill-empty", props={"value": "등록된 스킬 마켓이 없습니다."})
        )
    else:
        for idx, market in enumerate(skill_markets):
            name = market.get("name", f"market-{idx}")
            remaining = [m for m in skill_markets if m.get("name") != name]
            enabled_str = "활성" if market.get("enabled", True) else "비활성"
            children.append(
                Component(
                    type="list",
                    id=f"int-skill-{idx}",
                    props={"variant": "sub-card"},
                    children=[
                        Component(type="heading", id=f"int-skill-{idx}-h", props={"value": name, "level": 5}),
                        Component(
                            type="kv",
                            id=f"int-skill-{idx}-kv",
                            props={
                                "items": [
                                    {"key": "type", "value": market.get("type", "")},
                                    {"key": "enabled", "value": enabled_str},
                                ]
                            },
                        ),
                        Component(
                            type="button",
                            id=f"int-skill-{idx}-del",
                            props={
                                "label": "삭제",
                                "variant": "danger-sm",
                                "action": {
                                    "kind": "settings_write",
                                    "key": "skill_markets",
                                    "values": remaining,
                                },
                            },
                        ),
                    ],
                )
            )
    children.append(
        Component(
            type="form",
            id="int-market-add-form",
            props={
                "action": {"kind": "settings_append", "key": "skill_markets"},
                "submit_label": "+ 추가",
            },
            children=[
                Component(
                    type="field",
                    id="int-market-add-name",
                    props={"name": "name", "label": "이름", "value": "", "type": "text"},
                ),
                Component(
                    type="select",
                    id="int-market-add-type",
                    props={
                        "name": "type",
                        "label": "유형",
                        "value": "skills_sh",
                        "options": _SKILL_MARKET_TYPE_OPTIONS,
                    },
                ),
                Component(
                    type="field",
                    id="int-market-add-url",
                    props={"name": "url", "label": "URL (선택)", "value": "", "type": "text"},
                ),
                Component(
                    type="select",
                    id="int-market-add-enabled",
                    props={
                        "name": "enabled",
                        "label": "활성화",
                        "value": "true",
                        "options": _BOOL_OPTIONS,
                    },
                ),
            ],
        )
    )
    return Component(
        type="list",
        id="int-skill-markets",
        props={"variant": "settings-card"},
        children=children,
    )


# ── Tab: Safety & Permissions ─────────────────────────────────────────────

def _safety_tab(
    safety_blacklist: dict,
    safety_approval: list,
    safety_permissions: dict,
    tool_security: dict,
) -> Component:
    return Component(
        type="stack",
        id="tab-safety",
        props={"label": "안전 & 권한", "gap": "md"},
        children=[
            Component(type="heading", id="safety-h", props={"value": "안전 & 권한", "level": 3}),
            _blacklist_card(safety_blacklist),
            _approval_card(safety_approval),
            _permissions_card(safety_permissions),
            _tool_security_card(tool_security),
        ],
    )


def _blacklist_card(safety_blacklist: dict) -> Component:
    children: list[Component] = [
        Component(type="heading", id="safety-bl-h", props={"value": "차단 도구", "level": 4}),
        Component(type="text", id="safety-bl-d", props={"value": "도메인별로 차단할 도구 목록을 관리합니다."}),
    ]
    if not safety_blacklist:
        children.append(
            Component(type="text", id="safety-bl-empty", props={"value": "차단된 도구가 없습니다."})
        )
    else:
        for domain, tools in safety_blacklist.items():
            domain_children: list[Component] = [
                Component(type="heading", id=f"safety-bl-{domain}-h", props={"value": f"[{domain}]", "level": 5}),
            ]
            for tool in tools:
                # Build a new dict without this specific tool
                new_bl: dict = {}
                for d2, tlist in safety_blacklist.items():
                    remaining_tools = [t for t in tlist if t != tool] if d2 == domain else list(tlist)
                    if remaining_tools:
                        new_bl[d2] = remaining_tools
                domain_children.append(
                    _chip_with_delete(
                        chip_id=f"safety-bl-{domain}-{tool}",
                        label=tool,
                        delete_action={
                            "kind": "settings_write",
                            "key": "safety_blacklist",
                            "values": new_bl,
                        },
                    )
                )
            children.append(
                Component(
                    type="list",
                    id=f"safety-bl-domain-{domain}",
                    props={"variant": "sub-card"},
                    children=domain_children,
                )
            )
    children.append(
        Component(
            type="form",
            id="safety-blacklist-add-form",
            props={
                "action": {"kind": "settings_append", "key": "safety_blacklist"},
                "submit_label": "+ 추가",
            },
            children=[
                Component(
                    type="field",
                    id="safety-bl-add-domain",
                    props={"name": "domain", "label": "도메인", "value": "", "type": "text"},
                ),
                Component(
                    type="field",
                    id="safety-bl-add-tool",
                    props={"name": "tool", "label": "도구 이름", "value": "", "type": "text"},
                ),
            ],
        )
    )
    return Component(
        type="list",
        id="safety-blacklist",
        props={"variant": "settings-card"},
        children=children,
    )


def _approval_card(safety_approval: list) -> Component:
    children: list[Component] = [
        Component(type="heading", id="safety-ap-h", props={"value": "승인 필요 도구", "level": 4}),
        Component(type="text", id="safety-ap-d", props={"value": "실행 전 사용자 승인이 필요한 도구 목록입니다."}),
    ]
    if not safety_approval:
        children.append(
            Component(type="text", id="safety-ap-empty", props={"value": "승인 필요 도구가 없습니다."})
        )
    else:
        for tool in safety_approval:
            remaining = [t for t in safety_approval if t != tool]
            children.append(
                _chip_with_delete(
                    chip_id=f"safety-ap-{tool}",
                    label=tool,
                    delete_action={
                        "kind": "settings_write",
                        "key": "safety_approval",
                        "values": remaining,
                    },
                )
            )
    children.append(
        Component(
            type="form",
            id="safety-approval-add-form",
            props={
                "action": {"kind": "settings_append", "key": "safety_approval"},
                "submit_label": "+ 추가",
            },
            children=[
                Component(
                    type="field",
                    id="safety-ap-add-tool",
                    props={"name": "tool", "label": "도구 이름", "value": "", "type": "text"},
                ),
            ],
        )
    )
    return Component(
        type="list",
        id="safety-approval",
        props={"variant": "settings-card"},
        children=children,
    )


def _permissions_card(safety_permissions: dict) -> Component:
    admin_users = safety_permissions.get("admin_users", []) if isinstance(safety_permissions, dict) else []
    user_permissions = safety_permissions.get("user_permissions", {}) if isinstance(safety_permissions, dict) else {}

    children: list[Component] = [
        Component(type="heading", id="safety-perm-h", props={"value": "사용자 권한", "level": 4}),
        Component(type="heading", id="safety-perm-admin-h", props={"value": "관리자 사용자", "level": 5}),
    ]

    if not admin_users:
        children.append(
            Component(
                type="text",
                id="safety-perm-admin-empty",
                props={"value": "관리자 목록이 비어있으면 모든 사용자가 일반 권한 검사를 받습니다."},
            )
        )
    else:
        for user in admin_users:
            remaining = [u for u in admin_users if u != user]
            new_perms = {**safety_permissions, "admin_users": remaining}
            children.append(
                _chip_with_delete(
                    chip_id=f"safety-perm-admin-{user}",
                    label=user,
                    delete_action={
                        "kind": "settings_write",
                        "key": "safety_permissions",
                        "values": new_perms,
                    },
                )
            )
        children.append(
            Component(
                type="text",
                id="safety-perm-admin-note",
                props={"value": "관리자 목록이 비어있으면 모든 사용자가 일반 권한 검사를 받습니다."},
            )
        )

    children.append(
        Component(
            type="form",
            id="safety-admin-add-form",
            props={
                "action": {"kind": "settings_append", "key": "safety_permissions_admin_users"},
                "submit_label": "+ 추가",
            },
            children=[
                Component(
                    type="field",
                    id="safety-admin-add-user",
                    props={"name": "user", "label": "사용자 이름", "value": "", "type": "text"},
                ),
            ],
        )
    )

    children.append(
        Component(type="heading", id="safety-perm-up-h", props={"value": "사용자별 도구 화이트리스트", "level": 5})
    )
    if not user_permissions:
        children.append(
            Component(type="text", id="safety-perm-up-empty", props={"value": "사용자별 권한이 없습니다."})
        )
    else:
        kv_items = [
            {"key": user, "value": ", ".join(tools)}
            for user, tools in user_permissions.items()
        ]
        children.append(
            Component(type="kv", id="safety-perm-up-kv", props={"items": kv_items})
        )

    return Component(
        type="list",
        id="safety-permissions",
        props={"variant": "settings-card"},
        children=children,
    )


def _tool_security_card(tool_security: dict) -> Component:
    base_dir = tool_security.get("base_directory", "") if isinstance(tool_security, dict) else ""
    whitelist_enabled = tool_security.get("command_whitelist_enabled", False) if isinstance(tool_security, dict) else False
    # Read-only list fields
    list_fields = ("dangerous_patterns", "sensitive_file_patterns", "allowed_ssh_hosts", "command_whitelist")
    kv_items = []
    for field_name in list_fields:
        val = tool_security.get(field_name, []) if isinstance(tool_security, dict) else []
        kv_items.append({"key": field_name, "value": ", ".join(val) if val else "(없음)"})

    return Component(
        type="list",
        id="safety-tool-sec",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="safety-tool-sec-h", props={"value": "도구 보안 정책", "level": 4}),
            Component(type="text", id="safety-tool-sec-d", props={"value": "도구 실행에 적용되는 보안 정책입니다."}),
            Component(type="kv", id="safety-tool-sec-ro-kv", props={"items": kv_items}),
            Component(
                type="form",
                id="safety-tool-sec-form",
                props={
                    "action": {"kind": "settings_write", "key": "tool_security"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id="safety-tool-sec-basedir",
                        props={
                            "name": "base_directory",
                            "label": "기본 디렉토리",
                            "value": str(base_dir) if base_dir else "",
                            "type": "text",
                        },
                    ),
                    Component(
                        type="select",
                        id="safety-tool-sec-whitelist-enabled",
                        props={
                            "name": "command_whitelist_enabled",
                            "label": "커맨드 화이트리스트 활성화",
                            "value": str(whitelist_enabled).lower(),
                            "options": [
                                {"value": "true", "label": "활성화"},
                                {"value": "false", "label": "비활성화"},
                            ],
                        },
                    ),
                ],
            ),
        ],
    )


# ── Tab: Monitoring ───────────────────────────────────────────────────────

def _monitoring_tab(monitoring_config: dict, scheduler_cron: list) -> Component:
    return Component(
        type="stack",
        id="tab-monitoring",
        props={"label": "모니터링", "gap": "md"},
        children=[
            Component(type="heading", id="mon-h", props={"value": "모니터링", "level": 3}),
            _monitoring_rules_card(monitoring_config),
            _loop_protector_card(monitoring_config),
            _scheduler_cron_card(scheduler_cron),
        ],
    )


def _monitoring_rules_card(monitoring_config: dict) -> Component:
    rules = monitoring_config.get("rules", []) if isinstance(monitoring_config, dict) else []
    children: list[Component] = [
        Component(type="heading", id="mon-rules-h", props={"value": "모니터링 규칙", "level": 4}),
        Component(type="text", id="mon-rules-d", props={"value": "모니터링 규칙의 활성 상태를 관리합니다."}),
    ]
    if not rules:
        children.append(
            Component(type="text", id="mon-rules-empty", props={"value": "등록된 모니터링 규칙이 없습니다."})
        )
    else:
        for idx, rule in enumerate(rules):
            name = rule.get("name", f"rule-{idx}")
            enabled = rule.get("enabled", True)
            # Build full config with this rule's enabled flipped
            flipped_rules = []
            for r in rules:
                if r.get("name") == name:
                    flipped = dict(r)
                    flipped["enabled"] = not enabled
                    flipped_rules.append(flipped)
                else:
                    flipped_rules.append(dict(r))
            toggle_config = {**monitoring_config, "rules": flipped_rules}
            toggle_label = "비활성화" if enabled else "활성화"
            status_str = "활성" if enabled else "비활성"
            kv_items = [
                {"key": "severity", "value": str(rule.get("severity", ""))},
                {"key": "source", "value": str(rule.get("source", ""))},
                {"key": "interval_seconds", "value": str(rule.get("interval_seconds", ""))},
                {"key": "enabled", "value": status_str},
            ]
            if rule.get("description"):
                kv_items.insert(0, {"key": "description", "value": str(rule["description"])})
            children.append(
                Component(
                    type="list",
                    id=f"mon-rule-{idx}",
                    props={"variant": "sub-card"},
                    children=[
                        Component(type="heading", id=f"mon-rule-{idx}-h", props={"value": name, "level": 5}),
                        Component(type="kv", id=f"mon-rule-{idx}-kv", props={"items": kv_items}),
                        Component(
                            type="button",
                            id=f"mon-rule-{idx}-toggle",
                            props={
                                "label": toggle_label,
                                "variant": "secondary",
                                "action": {
                                    "kind": "settings_write",
                                    "key": "monitoring_config",
                                    "values": toggle_config,
                                },
                            },
                        ),
                    ],
                )
            )
    return Component(
        type="list",
        id="mon-rules",
        props={"variant": "settings-card"},
        children=children,
    )


def _loop_protector_card(monitoring_config: dict) -> Component:
    lp = monitoring_config.get("loop_protector", {}) if isinstance(monitoring_config, dict) else {}
    cooldown = lp.get("cooldown_minutes", 5) if isinstance(lp, dict) else 5
    max_actions = lp.get("max_auto_actions", 10) if isinstance(lp, dict) else 10
    return Component(
        type="list",
        id="mon-loop",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="mon-loop-h", props={"value": "루프 보호기", "level": 4}),
            Component(type="text", id="mon-loop-d", props={"value": "무한 루프 방지 정책을 설정합니다."}),
            Component(
                type="form",
                id="mon-loop-form",
                props={
                    "action": {
                        "kind": "settings_write",
                        "key": "monitoring_config",
                    },
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id="mon-loop-cooldown",
                        props={
                            "name": "cooldown_minutes",
                            "label": "쿨다운 (분)",
                            "value": str(cooldown),
                            "type": "number",
                        },
                    ),
                    Component(
                        type="field",
                        id="mon-loop-max-actions",
                        props={
                            "name": "max_auto_actions",
                            "label": "최대 자동 작업 수",
                            "value": str(max_actions),
                            "type": "number",
                        },
                    ),
                ],
            ),
        ],
    )


def _scheduler_cron_card(scheduler_cron: list) -> Component:
    children: list[Component] = [
        Component(type="heading", id="mon-cron-h", props={"value": "스케줄러 크론", "level": 4}),
        Component(type="text", id="mon-cron-d", props={"value": "예약된 크론 작업 목록입니다."}),
    ]
    if not scheduler_cron:
        children.append(
            Component(type="text", id="mon-cron-empty", props={"value": "등록된 크론 작업이 없습니다."})
        )
    else:
        for idx, entry in enumerate(scheduler_cron):
            name = entry.get("name", f"cron-{idx}")
            job_id = entry.get("id", name)
            remaining = [e for e in scheduler_cron if e.get("id", e.get("name")) != job_id]
            enabled_str = "활성" if entry.get("enabled", True) else "비활성"
            children.append(
                Component(
                    type="list",
                    id=f"mon-cron-{idx}",
                    props={"variant": "sub-card"},
                    children=[
                        Component(type="heading", id=f"mon-cron-{idx}-h", props={"value": name, "level": 5}),
                        Component(
                            type="kv",
                            id=f"mon-cron-{idx}-kv",
                            props={
                                "items": [
                                    {"key": "schedule", "value": entry.get("schedule", "")},
                                    {"key": "task", "value": entry.get("task", "")},
                                    {"key": "enabled", "value": enabled_str},
                                ]
                            },
                        ),
                        Component(
                            type="button",
                            id=f"mon-cron-{idx}-del",
                            props={
                                "label": "삭제",
                                "variant": "danger-sm",
                                "action": {
                                    "kind": "settings_write",
                                    "key": "scheduler_cron",
                                    "values": remaining,
                                },
                            },
                        ),
                    ],
                )
            )
    children.append(
        Component(
            type="form",
            id="mon-cron-add-form",
            props={
                "action": {"kind": "settings_append", "key": "scheduler_cron"},
                "submit_label": "+ 추가",
            },
            children=[
                Component(
                    type="field",
                    id="mon-cron-add-name",
                    props={"name": "name", "label": "이름", "value": "", "type": "text"},
                ),
                Component(
                    type="field",
                    id="mon-cron-add-schedule",
                    props={"name": "schedule", "label": "크론 표현식", "value": "", "type": "text", "placeholder": "0 9 * * 1"},
                ),
                Component(
                    type="field",
                    id="mon-cron-add-task",
                    props={"name": "task", "label": "작업", "value": "", "type": "text"},
                ),
                Component(
                    type="select",
                    id="mon-cron-add-enabled",
                    props={
                        "name": "enabled",
                        "label": "활성화",
                        "value": "true",
                        "options": _BOOL_OPTIONS,
                    },
                ),
            ],
        )
    )
    return Component(
        type="list",
        id="mon-scheduler-cron",
        props={"variant": "settings-card"},
        children=children,
    )


# ── Helper: resolve field value from store dict, falling back to defaults ──

def _resolve(store_dict: dict, defaults: dict, key: str) -> Any:
    """Return store value if present, else the default."""
    if isinstance(store_dict, dict) and key in store_dict:
        return store_dict[key]
    return defaults.get(key)


# ── Tab: Memory ────────────────────────────────────────────────────────────

def _memory_tab(memory_gc_config: dict) -> Component:
    return Component(
        type="stack",
        id="tab-memory",
        props={"label": "메모리", "gap": "md"},
        children=[
            Component(type="heading", id="mem-h", props={"value": "메모리", "level": 3}),
            _memory_gc_card(memory_gc_config),
        ],
    )


def _memory_gc_card(memory_gc_config: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(memory_gc_config, _MEMORY_GC_DEFAULTS, key))

    return Component(
        type="list",
        id="mem-gc",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="mem-gc-h", props={"value": "메모리 GC 설정", "level": 4}),
            Component(type="text", id="mem-gc-d", props={"value": "메모리 가비지 컬렉션 주기 및 임계값을 설정합니다."}),
            Component(
                type="form",
                id="mem-gc-form",
                props={
                    "action": {"kind": "settings_write", "key": "memory_gc_config"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id="mem-gc-interval",
                        props={
                            "name": "interval_seconds",
                            "label": "GC 주기 (초, 60-86400)",
                            "value": _v("interval_seconds"),
                            "type": "number",
                        },
                    ),
                    Component(
                        type="field",
                        id="mem-gc-decay",
                        props={
                            "name": "decay_threshold",
                            "label": "감쇠 임계값 (0.01-1.0)",
                            "value": _v("decay_threshold"),
                            "type": "number",
                            "step": "0.01",
                        },
                    ),
                    Component(
                        type="field",
                        id="mem-gc-notes",
                        props={
                            "name": "max_cached_notes",
                            "label": "최대 캐시 노트 수 (10-10000)",
                            "value": _v("max_cached_notes"),
                            "type": "number",
                        },
                    ),
                    Component(
                        type="field",
                        id="mem-gc-age",
                        props={
                            "name": "kg_max_age_days",
                            "label": "지식 그래프 최대 보존 기간 (일, 1-365)",
                            "value": _v("kg_max_age_days"),
                            "type": "number",
                        },
                    ),
                    Component(
                        type="field",
                        id="mem-gc-env-refresh",
                        props={
                            "name": "env_refresh_interval",
                            "label": "환경 갱신 주기 (초, 1-3600)",
                            "value": _v("env_refresh_interval"),
                            "type": "number",
                        },
                    ),
                ],
            ),
        ],
    )


# ── Tab: Advanced ──────────────────────────────────────────────────────────

def _advanced_tab(
    system_timeouts: dict,
    retry_config: dict,
    limits_config: dict,
    polling_config: dict,
    agent_timeouts: dict,
    logging_config: dict,
    vault_entries: list[dict] | None,
) -> Component:
    return Component(
        type="stack",
        id="tab-advanced",
        props={"label": "고급", "gap": "md"},
        children=[
            Component(type="heading", id="adv-h", props={"value": "고급", "level": 3}),
            _system_timeouts_card(system_timeouts),
            _retry_card(retry_config),
            _limits_card(limits_config),
            _polling_card(polling_config),
            _agent_timeouts_card(agent_timeouts),
            _logging_card(logging_config),
            _vault_card(vault_entries),
        ],
    )


def _system_timeouts_card(system_timeouts: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(system_timeouts, _SYSTEM_TIMEOUTS_DEFAULTS, key))

    fields = [
        ("tool_call", "도구 호출 타임아웃 (초, 1-3600)"),
        ("llm_api", "LLM API 타임아웃 (초, 1-3600)"),
        ("ssh_command", "SSH 명령 타임아웃 (초, 1-3600)"),
        ("health_check", "헬스 체크 타임아웃 (초, 1-3600)"),
        ("pypi_check", "PyPI 확인 타임아웃 (초, 1-3600)"),
        ("http_default", "HTTP 기본 타임아웃 (초, 1-3600)"),
        ("skill_discovery", "스킬 탐색 타임아웃 (초, 1-3600)"),
    ]
    return Component(
        type="list",
        id="adv-system-timeouts",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="adv-st-h", props={"value": "시스템 타임아웃", "level": 4}),
            Component(type="text", id="adv-st-d", props={"value": "각 작업 유형별 타임아웃을 설정합니다."}),
            Component(
                type="form",
                id="adv-st-form",
                props={
                    "action": {"kind": "settings_write", "key": "system_timeouts"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id=f"adv-st-{name}",
                        props={"name": name, "label": label, "value": _v(name), "type": "number"},
                    )
                    for name, label in fields
                ],
            ),
        ],
    )


def _retry_card(retry_config: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(retry_config, _RETRY_CONFIG_DEFAULTS, key))

    fields = [
        ("max_retries", "최대 재시도 횟수 (1-50)"),
        ("llm_max_retries", "LLM 최대 재시도 횟수 (1-50)"),
        ("gateway_max_retries", "게이트웨이 최대 재시도 횟수 (1-50)"),
        ("base_backoff", "기본 백오프 (초, 1-600)"),
        ("max_backoff", "최대 백오프 (초, 1-600)"),
        ("health_check_interval", "헬스 체크 간격 (초, 5-3600)"),
    ]
    return Component(
        type="list",
        id="adv-retry",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="adv-retry-h", props={"value": "재시도 정책", "level": 4}),
            Component(type="text", id="adv-retry-d", props={"value": "요청 실패 시 재시도 동작을 설정합니다."}),
            Component(
                type="form",
                id="adv-retry-form",
                props={
                    "action": {"kind": "settings_write", "key": "retry_config"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id=f"adv-retry-{name}",
                        props={"name": name, "label": label, "value": _v(name), "type": "number"},
                    )
                    for name, label in fields
                ],
            ),
        ],
    )


def _limits_card(limits_config: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(limits_config, _LIMITS_CONFIG_DEFAULTS, key))

    int_fields = [
        ("max_tools", "최대 도구 수 (1-200)"),
        ("max_context_tokens", "최대 컨텍스트 토큰 (100-1000000)"),
        ("max_per_domain_skills", "도메인별 최대 스킬 수 (1-50)"),
        ("audit_log_recent", "감사 로그 보존 수 (1-10000)"),
        ("embedding_cache_size", "임베딩 캐시 크기 (10-100000)"),
        ("top_roles_limit", "상위 역할 제한 (1-100)"),
        ("smart_retriever_token_budget", "스마트 검색 토큰 예산 (100-1000000)"),
        ("smart_retriever_limit", "스마트 검색 결과 제한 (1-100)"),
    ]
    children: list[Component] = [
        Component(type="heading", id="adv-limits-h", props={"value": "리소스 제한", "level": 4}),
        Component(type="text", id="adv-limits-d", props={"value": "시스템 리소스 및 작업 한도를 설정합니다."}),
    ]
    field_components: list[Component] = [
        Component(
            type="field",
            id=f"adv-limits-{name}",
            props={"name": name, "label": label, "value": _v(name), "type": "number"},
        )
        for name, label in int_fields
    ]
    field_components.append(
        Component(
            type="field",
            id="adv-limits-low-perf",
            props={
                "name": "low_performance_threshold",
                "label": "저성능 임계값 (0.0-1.0)",
                "value": _v("low_performance_threshold"),
                "type": "number",
                "step": "0.01",
            },
        )
    )
    children.append(
        Component(
            type="form",
            id="adv-limits-form",
            props={
                "action": {"kind": "settings_write", "key": "limits_config"},
                "submit_label": "저장",
            },
            children=field_components,
        )
    )
    return Component(
        type="list",
        id="adv-limits",
        props={"variant": "settings-card"},
        children=children,
    )


def _polling_card(polling_config: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(polling_config, _POLLING_CONFIG_DEFAULTS, key))

    fields = [
        ("signal_interval", "Signal 폴링 간격 (초, 1-86400)"),
        ("gmail_interval", "Gmail 폴링 간격 (초, 1-86400)"),
        ("update_check_interval", "업데이트 확인 간격 (초, 1-86400)"),
        ("data_flush_interval", "데이터 플러시 간격 (초, 1-86400)"),
        ("auto_cleanup_interval", "자동 정리 간격 (초, 1-86400)"),
    ]
    return Component(
        type="list",
        id="adv-polling",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="adv-polling-h", props={"value": "폴링 간격", "level": 4}),
            Component(type="text", id="adv-polling-d", props={"value": "각 서비스의 폴링 주기를 설정합니다."}),
            Component(
                type="form",
                id="adv-polling-form",
                props={
                    "action": {"kind": "settings_write", "key": "polling_config"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id=f"adv-polling-{name}",
                        props={"name": name, "label": label, "value": _v(name), "type": "number"},
                    )
                    for name, label in fields
                ],
            ),
        ],
    )


def _agent_timeouts_card(agent_timeouts: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(agent_timeouts, _AGENT_TIMEOUTS_DEFAULTS, key))

    fields = [
        ("tool_timeout", "도구 타임아웃 (초, 1-3600)"),
        ("chat_timeout", "채팅 타임아웃 (초, 1-3600)"),
        ("max_turns", "최대 턴 수 (1-100)"),
    ]
    return Component(
        type="list",
        id="adv-agent-timeouts",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="adv-at-h", props={"value": "에이전트 타임아웃", "level": 4}),
            Component(type="text", id="adv-at-d", props={"value": "에이전트 작업별 타임아웃 및 턴 제한을 설정합니다."}),
            Component(
                type="form",
                id="adv-at-form",
                props={
                    "action": {"kind": "settings_write", "key": "agent_timeouts"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="field",
                        id=f"adv-at-{name}",
                        props={"name": name, "label": label, "value": _v(name), "type": "number"},
                    )
                    for name, label in fields
                ],
            ),
        ],
    )


def _logging_card(logging_config: dict) -> Component:
    def _v(key: str) -> str:
        return str(_resolve(logging_config, _LOGGING_CONFIG_DEFAULTS, key))

    return Component(
        type="list",
        id="adv-logging",
        props={"variant": "settings-card"},
        children=[
            Component(type="heading", id="adv-log-h", props={"value": "로깅", "level": 4}),
            Component(type="text", id="adv-log-d", props={"value": "로그 레벨과 출력 형식을 설정합니다."}),
            Component(
                type="form",
                id="adv-log-form",
                props={
                    "action": {"kind": "settings_write", "key": "logging_config"},
                    "submit_label": "저장",
                },
                children=[
                    Component(
                        type="select",
                        id="adv-log-level",
                        props={
                            "name": "level",
                            "label": "로그 레벨",
                            "value": _v("level"),
                            "options": _LOG_LEVEL_OPTIONS,
                        },
                    ),
                    Component(
                        type="select",
                        id="adv-log-format",
                        props={
                            "name": "format",
                            "label": "로그 형식",
                            "value": _v("format"),
                            "options": _LOG_FORMAT_OPTIONS,
                        },
                    ),
                ],
            ),
        ],
    )


def _vault_entry_row(entry: dict, index: int) -> Component:
    """Render a single vault entry: id label, masked indicator, stored_at, delete button."""
    cred_id = entry.get("id", "")
    stored_at = _format_timestamp(entry.get("stored_at"))
    row_id = f"adv-vault-entry-{index}"
    return Component(
        type="stack",
        id=row_id,
        props={"gap": "xs"},
        children=[
            Component(
                type="stack",
                id=f"{row_id}-top",
                props={"direction": "horizontal", "gap": "sm", "align": "center"},
                children=[
                    Component(
                        type="text",
                        id=f"{row_id}-id",
                        props={"value": cred_id, "variant": "code"},
                    ),
                    Component(
                        type="badge",
                        id=f"{row_id}-masked",
                        props={"value": "●●●● 저장됨"},
                    ),
                    Component(
                        type="button",
                        id=f"{row_id}-del",
                        props={
                            "label": "삭제",
                            "variant": "danger-sm",
                            "action": {
                                "kind": "credential_delete",
                                "credential_id": cred_id,
                            },
                        },
                    ),
                ],
            ),
            Component(
                type="text",
                id=f"{row_id}-ts",
                props={"value": f"저장 시각: {stored_at}", "variant": "muted"},
            ),
        ],
    )


def _vault_card(vault_entries: list[dict] | None) -> Component:
    """Render the credential vault management card.

    vault_entries=None  → db lacked list_settings_by_prefix (unavailable)
    vault_entries=[]    → db returned no entries (empty)
    vault_entries=[...] → one row per entry + delete button each
    """
    children: list[Component] = [
        Component(type="heading", id="adv-vault-h", props={"value": "자격증명 금고", "level": 4}),
        Component(type="text", id="adv-vault-d", props={"value": "저장된 자격증명을 관리합니다."}),
    ]

    if vault_entries is None:
        children.append(
            Component(
                type="text",
                id="adv-vault-unavailable",
                props={"value": "자격증명 금고를 불러올 수 없습니다."},
            )
        )
    elif not vault_entries:
        children.append(
            Component(
                type="text",
                id="adv-vault-empty",
                props={"value": "저장된 자격증명이 없습니다."},
            )
        )
    else:
        for i, entry in enumerate(vault_entries):
            children.append(_vault_entry_row(entry, i))

    # Add / rotate form — always present so users can add new credentials.
    children.append(
        Component(
            type="heading",
            id="adv-vault-form-h",
            props={"value": "자격증명 추가 / 교체", "level": 5},
        )
    )
    children.append(
        Component(
            type="form",
            id="adv-vault-form",
            props={
                "action": {"kind": "credential_store"},
                "submit_label": "저장",
            },
            children=[
                Component(
                    type="field",
                    id="adv-vault-form-id",
                    props={
                        "name": "credential_id",
                        "label": "자격증명 ID",
                        "value": "",
                        "type": "text",
                        "placeholder": "예: ssh:host1, messenger:slack",
                    },
                ),
                Component(
                    type="field",
                    id="adv-vault-form-value",
                    props={
                        "name": "value",
                        "label": "값 (비밀번호 / 토큰)",
                        "value": "",
                        "type": "password",
                    },
                ),
            ],
        )
    )

    return Component(
        type="list",
        id="adv-vault",
        props={"variant": "settings-card"},
        children=children,
    )


# ── Placeholder Tabs ───────────────────────────────────────────────────────

def _placeholder_tab(tab_id: str, label: str, message: str) -> Component:
    return Component(
        type="stack",
        id=tab_id,
        props={"label": label, "gap": "md"},
        children=[
            Component(type="heading", id=f"{tab_id}-h", props={"value": label, "level": 3}),
            Component(type="text", id=f"{tab_id}-msg", props={"value": message}),
        ],
    )
