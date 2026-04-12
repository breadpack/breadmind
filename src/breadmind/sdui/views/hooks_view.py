"""Hooks admin view: 3-tab layout for hooks-v2 Phase 3.

Tabs:
  - Hooks:  table fed by ``/api/hooks/list`` + form to create a new shell hook.
  - Traces: live stream bound to ``/ws/hooks/traces`` (HTTP fallback
            ``/api/hooks/traces?limit=100``).
  - Stats:  table fed by ``/api/hooks/stats``.

Returned as a plain ``dict`` via :meth:`UISpec.to_dict` so that route handlers
can ship it directly to the SDUI renderer.
"""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import Component, UISpec

_EVENT_OPTIONS = [
    {"value": "pre_tool_use", "label": "pre_tool_use"},
    {"value": "post_tool_use", "label": "post_tool_use"},
    {"value": "user_prompt_submit", "label": "user_prompt_submit"},
    {"value": "llm_request", "label": "llm_request"},
    {"value": "messenger_received", "label": "messenger_received"},
]

_TYPE_OPTIONS = [
    {"value": "shell", "label": "shell"},
    {"value": "prompt", "label": "prompt (LLM)"},
    {"value": "agent", "label": "agent (multi-turn)"},
    {"value": "http", "label": "http (webhook)"},
]

_HOOKS_COLUMNS: list[dict[str, Any]] = [
    {"field": "hook_id", "label": "ID"},
    {"field": "event", "label": "Event"},
    {"field": "type", "label": "Type"},
    {"field": "priority", "label": "Priority"},
    {"field": "enabled", "label": "Enabled"},
    {"field": "source", "label": "Source"},
]

_TRACE_COLUMNS: list[dict[str, Any]] = [
    {"field": "timestamp", "label": "Time"},
    {"field": "hook_id", "label": "Hook"},
    {"field": "event", "label": "Event"},
    {"field": "decision", "label": "Decision"},
    {"field": "duration_ms", "label": "ms"},
    {"field": "reason", "label": "Reason"},
]

_STATS_COLUMNS: list[dict[str, Any]] = [
    {"field": "hook_id", "label": "Hook"},
    {"field": "total", "label": "Total"},
    {"field": "avg_duration_ms", "label": "Avg ms"},
    {"field": "block_count", "label": "Blocks"},
    {"field": "modify_count", "label": "Modifies"},
    {"field": "error_count", "label": "Errors"},
]


def _hooks_tab() -> Component:
    """Tab 1: list existing hooks and expose a create form."""
    return Component(
        type="stack",
        id="hooks-tab-hooks",
        props={"label": "Hooks", "gap": "md"},
        children=[
            Component(
                type="heading",
                id="hooks-list-h",
                props={"value": "등록된 훅", "level": 3},
            ),
            Component(
                type="table",
                id="hooks-list-table",
                props={
                    "columns": _HOOKS_COLUMNS,
                    "rows": [],
                    "data_source": "/api/hooks/list",
                    "data_path": "hooks",
                    "row_actions": [
                        {
                            "label": "삭제",
                            "method": "DELETE",
                            "url_template": "/api/hooks/{hook_id}",
                            "tone": "danger",
                        },
                    ],
                },
            ),
            Component(
                type="heading",
                id="hooks-new-h",
                props={"value": "새 Shell 훅", "level": 4},
            ),
            Component(
                type="form",
                id="hooks-new-form",
                props={
                    "action": {
                        "kind": "http_request",
                        "method": "POST",
                        "url": "/api/hooks/",
                    },
                    "submit_label": "생성",
                },
                children=[
                    Component(
                        type="field",
                        id="hooks-new-id",
                        props={
                            "name": "hook_id",
                            "label": "ID",
                            "type": "text",
                        },
                    ),
                    Component(
                        type="select",
                        id="hooks-new-event",
                        props={
                            "name": "event",
                            "label": "이벤트",
                            "options": _EVENT_OPTIONS,
                        },
                    ),
                    Component(
                        type="select",
                        id="hooks-new-type",
                        props={
                            "name": "type",
                            "label": "타입",
                            "options": _TYPE_OPTIONS,
                        },
                    ),
                    Component(
                        type="field",
                        id="hooks-new-tool-pattern",
                        props={
                            "name": "tool_pattern",
                            "label": "도구 패턴",
                            "type": "text",
                            "placeholder": "예: Bash, Write, *",
                        },
                    ),
                    Component(
                        type="field",
                        id="hooks-new-priority",
                        props={
                            "name": "priority",
                            "label": "우선순위",
                            "type": "number",
                            "value": 0,
                        },
                    ),
                    Component(
                        type="field",
                        id="hooks-new-command",
                        props={
                            "name": "command",
                            "label": "Shell 명령",
                            "type": "textarea",
                        },
                    ),
                ],
            ),
        ],
    )


def _traces_tab() -> Component:
    """Tab 2: live trace stream with HTTP fallback."""
    return Component(
        type="stack",
        id="hooks-tab-traces",
        props={"label": "Traces", "gap": "md"},
        children=[
            Component(
                type="heading",
                id="hooks-traces-h",
                props={"value": "실시간 트레이스", "level": 3},
            ),
            Component(
                type="table",
                id="hooks-traces-table",
                props={
                    "columns": _TRACE_COLUMNS,
                    "rows": [],
                    "live": True,
                    "ws_url": "/ws/hooks/traces",
                    "data_source": "/api/hooks/traces?limit=100",
                    "data_path": "traces",
                },
            ),
        ],
    )


def _stats_tab() -> Component:
    """Tab 3: aggregated stats table."""
    return Component(
        type="stack",
        id="hooks-tab-stats",
        props={"label": "Stats", "gap": "md"},
        children=[
            Component(
                type="heading",
                id="hooks-stats-h",
                props={"value": "통계", "level": 3},
            ),
            Component(
                type="table",
                id="hooks-stats-table",
                props={
                    "columns": _STATS_COLUMNS,
                    "rows": [],
                    "data_source": "/api/hooks/stats",
                    "data_path": "stats",
                },
            ),
        ],
    )


def build_hooks_view() -> dict:
    """Return the SDUI schema for the Hooks admin page with 3 tabs.

    The schema follows the project's :class:`Component`/:class:`UISpec`
    conventions (see ``settings_view.py``): tabs are ``type="stack"`` children
    of a ``type="tabs"`` container, and each tab declares its ``label`` via
    ``props``.  The result is serialized to a plain ``dict`` so web routes
    can return it directly as JSON.
    """
    tabs = [
        _hooks_tab(),
        _traces_tab(),
        _stats_tab(),
    ]

    spec = UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="hooks",
            props={"title": "Hooks"},
            children=[
                Component(
                    type="heading",
                    id="hooks-h",
                    props={"value": "Hooks", "level": 2},
                ),
                Component(
                    type="tabs",
                    id="hooks-tabs",
                    props={},
                    children=tabs,
                ),
            ],
        ),
    )
    return spec.to_dict()
