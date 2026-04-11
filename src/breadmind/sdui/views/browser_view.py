"""Browser view: sessions and macros."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import Component, UISpec


async def build(db: Any, *, browser_engine: Any = None, **_kwargs: Any) -> UISpec:
    """Build the browser view UISpec.

    Shows active browser sessions and saved macros. The browser_engine is
    optional — when absent or broken, the view degrades gracefully to empty
    sections.
    """
    sessions = await _safe_list_sessions(browser_engine)
    macros = await _safe_list_macros(browser_engine)

    sessions_children: list[Component] = [
        Component(type="heading", id="sh", props={"value": "활성 브라우저 세션", "level": 3}),
        Component(type="text", id="scount", props={"value": f"총 {len(sessions)}개"}),
        Component(
            type="button",
            id="new-session",
            props={
                "label": "+ 새 세션",
                "variant": "primary",
                "action": {
                    "kind": "intervention",
                    "category": "browser",
                    "operation": "new_session",
                },
            },
        ),
    ]
    if not sessions:
        sessions_children.append(
            Component(type="text", id="empty-sessions", props={"value": "활성 세션 없음"})
        )
    else:
        sessions_children.append(
            Component(
                type="stack",
                id="sessions-list",
                props={"gap": "sm"},
                children=[_session_card(s) for s in sessions],
            )
        )
    sessions_section = Component(
        type="stack",
        id="sessions-section",
        props={"gap": "md"},
        children=sessions_children,
    )

    macros_children: list[Component] = [
        Component(type="heading", id="mh", props={"value": "저장된 매크로", "level": 3}),
        Component(type="text", id="mcount", props={"value": f"총 {len(macros)}개"}),
    ]
    if not macros:
        macros_children.append(
            Component(type="text", id="empty-macros", props={"value": "저장된 매크로 없음"})
        )
    else:
        macros_children.append(
            Component(
                type="stack",
                id="macros-list",
                props={"gap": "sm"},
                children=[_macro_card(m) for m in macros],
            )
        )
    macros_section = Component(
        type="stack",
        id="macros-section",
        props={"gap": "md"},
        children=macros_children,
    )

    live_section = Component(
        type="stack",
        id="live-section",
        props={"gap": "md"},
        children=[
            Component(type="heading", id="lh", props={"value": "라이브 뷰", "level": 3}),
            Component(
                type="text",
                id="live-soon",
                props={"value": "라이브 뷰는 곧 지원 예정입니다."},
            ),
        ],
    )

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="browser",
            props={"title": "브라우저"},
            children=[
                Component(
                    type="heading",
                    id="h",
                    props={"value": "브라우저 자동화", "level": 2},
                ),
                Component(
                    type="tabs",
                    id="tabs",
                    props={},
                    children=[sessions_section, macros_section, live_section],
                ),
            ],
        ),
    )


def _session_card(s: dict) -> Component:
    sid = str(s.get("id", "unknown"))
    return Component(
        type="list",
        id=f"sess-{sid}",
        props={"variant": "session"},
        children=[
            Component(
                type="heading",
                id=f"sn-{sid}",
                props={"value": s.get("name", sid), "level": 4},
            ),
            Component(
                type="kv",
                id=f"sk-{sid}",
                props={
                    "items": [
                        {"key": "ID", "value": sid},
                        {"key": "모드", "value": str(s.get("mode", "?"))},
                        {"key": "탭", "value": str(s.get("tab_count", 0))},
                        {"key": "지속성", "value": "예" if s.get("persistent") else "아니오"},
                    ]
                },
            ),
            Component(
                type="button",
                id=f"close-{sid}",
                props={
                    "label": "닫기",
                    "variant": "ghost",
                    "action": {
                        "kind": "intervention",
                        "category": "browser",
                        "operation": "close_session",
                        "session_id": sid,
                    },
                },
            ),
        ],
    )


def _macro_card(m: dict) -> Component:
    mid = str(m.get("id", "unknown"))
    steps = m.get("steps", []) or []
    exec_count = m.get("execution_count", 0)
    return Component(
        type="list",
        id=f"macro-{mid}",
        props={"variant": "macro"},
        children=[
            Component(
                type="heading",
                id=f"mn-{mid}",
                props={"value": m.get("name", mid), "level": 4},
            ),
            Component(
                type="text",
                id=f"mc-{mid}",
                props={"value": f"단계 {len(steps)}개 · 실행 {exec_count}회"},
            ),
            Component(
                type="button",
                id=f"run-{mid}",
                props={
                    "label": "실행",
                    "variant": "primary",
                    "action": {
                        "kind": "intervention",
                        "category": "browser",
                        "operation": "run_macro",
                        "macro_id": mid,
                    },
                },
            ),
        ],
    )


async def _safe_list_sessions(engine: Any) -> list[dict]:
    if engine is None:
        return []
    try:
        # BrowserEngine exposes _session_mgr.list_sessions() internally.
        mgr = getattr(engine, "_session_mgr", None)
        if mgr is not None and hasattr(mgr, "list_sessions"):
            result = mgr.list_sessions()
            return [_normalize(s) for s in result]
        for attr in ("list_sessions", "sessions"):
            if hasattr(engine, attr):
                obj = getattr(engine, attr)
                result = obj() if callable(obj) else obj
                if hasattr(result, "__await__"):
                    result = await result
                iterable = result.values() if isinstance(result, dict) else result
                return [_normalize(s) for s in iterable]
    except Exception:
        return []
    return []


async def _safe_list_macros(engine: Any) -> list[dict]:
    if engine is None:
        return []
    try:
        # BrowserEngine exposes _macro_store (MacroStore) with list_all().
        store = getattr(engine, "_macro_store", None) or getattr(engine, "macro_store", None)
        if store is not None and hasattr(store, "list_all"):
            result = store.list_all()
            if hasattr(result, "__await__"):
                result = await result
            return [_normalize(m) for m in result]
        for attr in ("list_macros", "macros"):
            if hasattr(engine, attr):
                obj = getattr(engine, attr)
                result = obj() if callable(obj) else obj
                if hasattr(result, "__await__"):
                    result = await result
                iterable = result.values() if isinstance(result, dict) else result
                return [_normalize(m) for m in iterable]
    except Exception:
        return []
    return []


def _normalize(item: Any) -> dict:
    if isinstance(item, dict):
        return item
    # BrowserMacro / BrowserSession dataclass-ish objects
    return {
        "id": getattr(item, "id", "unknown"),
        "name": getattr(item, "name", ""),
        "mode": getattr(item, "mode", None),
        "tab_count": getattr(item, "tab_count", 0),
        "persistent": getattr(item, "persistent", False),
        "steps": getattr(item, "steps", []),
        "execution_count": getattr(item, "execution_count", 0),
    }
