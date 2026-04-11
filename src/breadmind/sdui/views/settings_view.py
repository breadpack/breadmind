"""Settings view: configuration display in tabbed layout.

Renders BreadMind settings across four tabs: System, Safety, Timeouts & Retry,
and About. Settings are read from the injected ``settings_store`` when present;
all store access is wrapped in try/except so the view always renders structure,
even when the store is missing, broken, or the keys are absent.

The Phase 2 view is read-only — the Timeouts tab includes a placeholder form
for future write wiring, but no mutations are performed here.
"""
from __future__ import annotations

import logging
from typing import Any

from breadmind.sdui.spec import Component, UISpec

logger = logging.getLogger(__name__)

_PLACEHOLDER = "N/A"


async def build(db: Any, *, settings_store: Any = None, **_kwargs: Any) -> UISpec:
    """Build the settings UISpec.

    Parameters
    ----------
    db:
        Database handle (unused today — kept for signature parity with other
        views and possible future usage like audit logs).
    settings_store:
        Optional store providing ``get_setting(key)``. When ``None`` or when a
        call raises, the view falls back to placeholder values.
    """
    system_data = await _safe_load_system(settings_store)
    safety_data = await _safe_load_safety(settings_store)
    timeouts_data = await _safe_load_timeouts(settings_store)

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="settings",
            props={"title": "설정"},
            children=[
                Component(
                    type="heading",
                    id="settings-heading",
                    props={"value": "설정", "level": 2},
                ),
                Component(
                    type="tabs",
                    id="settings-tabs",
                    props={},
                    children=[
                        _system_tab(system_data),
                        _safety_tab(safety_data),
                        _timeouts_tab(timeouts_data),
                        _about_tab(),
                    ],
                ),
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Safe loaders
# ---------------------------------------------------------------------------

async def _store_get(store: Any, key: str, default: Any = None) -> Any:
    """Call ``store.get_setting(key)`` defensively.

    Returns ``default`` on any failure (missing store, missing method, raised
    exception, or ``None`` value).
    """
    if store is None:
        return default
    try:
        getter = getattr(store, "get_setting", None)
        if getter is None:
            return default
        value = await getter(key)
        return default if value is None else value
    except Exception as exc:  # noqa: BLE001
        logger.debug("settings_view: store.get_setting(%s) failed: %s", key, exc)
        return default


async def _safe_load_system(store: Any) -> dict[str, Any]:
    llm = await _store_get(store, "llm", {}) or {}
    database = await _store_get(store, "database", {}) or {}
    usage = await _store_get(store, "usage", {}) or {}
    monitoring = await _store_get(store, "monitoring_status", {}) or {}

    return {
        "llm_provider": llm.get("default_provider", _PLACEHOLDER) if isinstance(llm, dict) else _PLACEHOLDER,
        "llm_model": llm.get("default_model", _PLACEHOLDER) if isinstance(llm, dict) else _PLACEHOLDER,
        "tool_call_max_turns": llm.get("tool_call_max_turns", _PLACEHOLDER) if isinstance(llm, dict) else _PLACEHOLDER,
        "db_host": database.get("host", _PLACEHOLDER) if isinstance(database, dict) else _PLACEHOLDER,
        "db_port": database.get("port", _PLACEHOLDER) if isinstance(database, dict) else _PLACEHOLDER,
        "db_name": database.get("name", _PLACEHOLDER) if isinstance(database, dict) else _PLACEHOLDER,
        "tokens_in": usage.get("tokens_in", _PLACEHOLDER) if isinstance(usage, dict) else _PLACEHOLDER,
        "tokens_out": usage.get("tokens_out", _PLACEHOLDER) if isinstance(usage, dict) else _PLACEHOLDER,
        "cost": usage.get("cost", _PLACEHOLDER) if isinstance(usage, dict) else _PLACEHOLDER,
        "monitoring_running": monitoring.get("running", _PLACEHOLDER) if isinstance(monitoring, dict) else _PLACEHOLDER,
        "monitoring_rules": monitoring.get("rules", _PLACEHOLDER) if isinstance(monitoring, dict) else _PLACEHOLDER,
        "monitoring_events": monitoring.get("events_total", _PLACEHOLDER) if isinstance(monitoring, dict) else _PLACEHOLDER,
    }


async def _safe_load_safety(store: Any) -> dict[str, Any]:
    safety = await _store_get(store, "safety", {}) or {}
    if not isinstance(safety, dict):
        safety = {}
    blacklist = safety.get("blacklist", {}) if isinstance(safety.get("blacklist"), dict) else {}
    return {
        "blacklist_tools": list(blacklist.get("tools", []) or []),
        "blacklist_paths": list(blacklist.get("paths", []) or []),
        "require_approval": list(safety.get("require_approval", []) or []),
        "admin_users": list(safety.get("admin_users", []) or []),
    }


async def _safe_load_timeouts(store: Any) -> dict[str, Any]:
    timeouts = await _store_get(store, "timeouts_system", {}) or {}
    retry = await _store_get(store, "retry", {}) or {}
    if not isinstance(timeouts, dict):
        timeouts = {}
    if not isinstance(retry, dict):
        retry = {}
    return {
        "tool_call": timeouts.get("tool_call", _PLACEHOLDER),
        "llm_api": timeouts.get("llm_api", _PLACEHOLDER),
        "ssh_command": timeouts.get("ssh_command", _PLACEHOLDER),
        "health_check": timeouts.get("health_check", _PLACEHOLDER),
        "max_retries": retry.get("max_retries", _PLACEHOLDER),
        "llm_max_retries": retry.get("llm_max_retries", _PLACEHOLDER),
        "base_backoff": retry.get("base_backoff", _PLACEHOLDER),
        "max_backoff": retry.get("max_backoff", _PLACEHOLDER),
    }


# ---------------------------------------------------------------------------
# Tab builders
# ---------------------------------------------------------------------------

def _kv_item(key: str, value: Any) -> dict[str, Any]:
    return {"key": key, "value": _fmt(value)}


def _fmt(value: Any) -> str:
    if value is None:
        return _PLACEHOLDER
    if isinstance(value, bool):
        return "예" if value else "아니오"
    return str(value)


def _system_tab(data: dict[str, Any]) -> Component:
    llm_items = [
        _kv_item("LLM Provider", data.get("llm_provider")),
        _kv_item("Default Model", data.get("llm_model")),
        _kv_item("Tool Call Max Turns", data.get("tool_call_max_turns")),
    ]
    db_items = [
        _kv_item("Host", data.get("db_host")),
        _kv_item("Port", data.get("db_port")),
        _kv_item("Database", data.get("db_name")),
    ]
    usage_items = [
        _kv_item("Tokens In", data.get("tokens_in")),
        _kv_item("Tokens Out", data.get("tokens_out")),
        _kv_item("Cost", data.get("cost")),
    ]
    monitoring_items = [
        _kv_item("Running", data.get("monitoring_running")),
        _kv_item("Rules", data.get("monitoring_rules")),
        _kv_item("Events Total", data.get("monitoring_events")),
    ]
    return Component(
        type="stack",
        id="tab-system",
        props={"label": "시스템", "gap": "md"},
        children=[
            Component(type="heading", id="tab-system-h", props={"value": "시스템", "level": 3}),
            Component(type="heading", id="tab-system-llm-h", props={"value": "LLM", "level": 4}),
            Component(type="kv", id="tab-system-llm-kv", props={"items": llm_items}),
            Component(type="divider", id="tab-system-div1", props={}),
            Component(type="heading", id="tab-system-db-h", props={"value": "데이터베이스", "level": 4}),
            Component(type="kv", id="tab-system-db-kv", props={"items": db_items}),
            Component(type="divider", id="tab-system-div2", props={}),
            Component(type="heading", id="tab-system-usage-h", props={"value": "사용량", "level": 4}),
            Component(type="kv", id="tab-system-usage-kv", props={"items": usage_items}),
            Component(type="divider", id="tab-system-div3", props={}),
            Component(type="heading", id="tab-system-mon-h", props={"value": "모니터링 상태", "level": 4}),
            Component(type="kv", id="tab-system-mon-kv", props={"items": monitoring_items}),
        ],
    )


def _safety_list(list_id: str, values: list[Any], empty_text: str) -> Component:
    if not values:
        return Component(
            type="text",
            id=f"{list_id}-empty",
            props={"value": empty_text},
        )
    children = [
        Component(
            type="text",
            id=f"{list_id}-item-{idx}",
            props={"value": str(v)},
        )
        for idx, v in enumerate(values)
    ]
    return Component(
        type="list",
        id=list_id,
        props={"variant": "plain"},
        children=children,
    )


def _safety_tab(data: dict[str, Any]) -> Component:
    return Component(
        type="stack",
        id="tab-safety",
        props={"label": "안전", "gap": "md"},
        children=[
            Component(type="heading", id="tab-safety-h", props={"value": "안전 규칙", "level": 3}),
            Component(type="heading", id="tab-safety-bt-h", props={"value": "차단된 도구", "level": 4}),
            _safety_list("tab-safety-bt", data.get("blacklist_tools", []), "차단된 도구가 없습니다."),
            Component(type="heading", id="tab-safety-bp-h", props={"value": "차단된 경로", "level": 4}),
            _safety_list("tab-safety-bp", data.get("blacklist_paths", []), "차단된 경로가 없습니다."),
            Component(type="heading", id="tab-safety-ra-h", props={"value": "승인 필요", "level": 4}),
            _safety_list("tab-safety-ra", data.get("require_approval", []), "승인 규칙이 없습니다."),
            Component(type="heading", id="tab-safety-au-h", props={"value": "관리자", "level": 4}),
            _safety_list("tab-safety-au", data.get("admin_users", []), "관리자가 지정되지 않았습니다."),
        ],
    )


def _timeouts_tab(data: dict[str, Any]) -> Component:
    timeout_items = [
        _kv_item("Tool Call", data.get("tool_call")),
        _kv_item("LLM API", data.get("llm_api")),
        _kv_item("SSH Command", data.get("ssh_command")),
        _kv_item("Health Check", data.get("health_check")),
    ]
    retry_items = [
        _kv_item("Max Retries", data.get("max_retries")),
        _kv_item("LLM Max Retries", data.get("llm_max_retries")),
        _kv_item("Base Backoff", data.get("base_backoff")),
        _kv_item("Max Backoff", data.get("max_backoff")),
    ]
    placeholder_form = Component(
        type="form",
        id="tab-timeouts-form",
        props={
            "label": "편집 (읽기 전용 — Phase 2)",
            "read_only": True,
            "action": None,
        },
        children=[
            Component(
                type="field",
                id="tab-timeouts-field-tool-call",
                props={
                    "name": "tool_call",
                    "label": "Tool Call Timeout",
                    "value": _fmt(data.get("tool_call")),
                    "read_only": True,
                },
            ),
            Component(
                type="field",
                id="tab-timeouts-field-llm-api",
                props={
                    "name": "llm_api",
                    "label": "LLM API Timeout",
                    "value": _fmt(data.get("llm_api")),
                    "read_only": True,
                },
            ),
            Component(
                type="field",
                id="tab-timeouts-field-max-retries",
                props={
                    "name": "max_retries",
                    "label": "Max Retries",
                    "value": _fmt(data.get("max_retries")),
                    "read_only": True,
                },
            ),
        ],
    )
    return Component(
        type="stack",
        id="tab-timeouts",
        props={"label": "타임아웃/재시도", "gap": "md"},
        children=[
            Component(type="heading", id="tab-timeouts-h", props={"value": "타임아웃 & 재시도", "level": 3}),
            Component(type="heading", id="tab-timeouts-to-h", props={"value": "타임아웃", "level": 4}),
            Component(type="kv", id="tab-timeouts-to-kv", props={"items": timeout_items}),
            Component(type="divider", id="tab-timeouts-div", props={}),
            Component(type="heading", id="tab-timeouts-re-h", props={"value": "재시도", "level": 4}),
            Component(type="kv", id="tab-timeouts-re-kv", props={"items": retry_items}),
            Component(type="divider", id="tab-timeouts-div2", props={}),
            placeholder_form,
        ],
    )


def _about_tab() -> Component:
    about_md = (
        "## BreadMind\n\n"
        "자연어로 Kubernetes, Proxmox, OpenWrt를 관리하는 AI 인프라 에이전트.\n\n"
        "- 다중 LLM 지원\n"
        "- 6개 메신저 통합\n"
        "- MCP 프로토콜\n"
        "- 플러그인 시스템\n"
        "- Commander/Worker 분산 아키텍처\n"
    )
    return Component(
        type="stack",
        id="tab-about",
        props={"label": "정보", "gap": "md"},
        children=[
            Component(type="heading", id="tab-about-h", props={"value": "정보", "level": 3}),
            Component(type="text", id="tab-about-version", props={"value": "Version: dev"}),
            Component(type="markdown", id="tab-about-md", props={"value": about_md}),
            Component(
                type="text",
                id="tab-about-link",
                props={"value": "https://github.com/BreakPack/breadmind"},
            ),
        ],
    )
