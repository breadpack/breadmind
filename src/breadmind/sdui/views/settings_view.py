"""Settings view: Phase 1 editable settings + Phase 2+ placeholder tabs.

Phase 1 (editable):
  - Quick Start: LLM provider, API keys, persona
  - Agent Behavior: prompts, instructions, embedding backend

Phase 2+ (placeholder):
  - Integrations, Safety & Permissions, Monitoring, Memory, Advanced

All forms emit ``settings_write`` actions; the action handler validates and
persists via the settings store or credential vault.
"""
from __future__ import annotations

import logging
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


async def build(db: Any, *, settings_store: Any = None, **_kwargs: Any) -> UISpec:
    llm = await _safe_get(settings_store, "llm", {}) or {}
    persona = await _safe_get(settings_store, "persona", {}) or {}
    prompts = await _safe_get(settings_store, "custom_prompts", {}) or {}
    instructions = await _safe_get(settings_store, "custom_instructions", "") or ""
    embedding = await _safe_get(settings_store, "embedding_config", {}) or {}
    apikey_status = {}
    for name, _ in _API_KEYS:
        apikey_status[name] = await _safe_get(settings_store, f"apikey:{name}", None)

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="settings",
            props={"title": "설정"},
            children=[
                Component(type="heading", id="settings-h", props={"value": "설정", "level": 2}),
                Component(
                    type="tabs",
                    id="settings-tabs",
                    props={},
                    children=[
                        _quick_start_tab(llm, persona, apikey_status),
                        _agent_behavior_tab(prompts, instructions, embedding),
                        _placeholder_tab("tab-integrations", "통합", "MCP 서버, 스킬 마켓, 메신저는 Phase 2에서 편집 가능합니다."),
                        _placeholder_tab("tab-safety", "안전 & 권한", "Phase 2에서 사용 가능."),
                        _placeholder_tab("tab-monitoring", "모니터링", "Phase 2에서 사용 가능."),
                        _placeholder_tab("tab-memory", "메모리", "Phase 3에서 사용 가능."),
                        _placeholder_tab("tab-advanced", "고급", "Phase 3에서 사용 가능."),
                    ],
                ),
            ],
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
