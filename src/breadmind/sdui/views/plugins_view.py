"""Plugins view: list installed plugins with enable/disable/uninstall actions."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import Component, UISpec


async def build(db: Any, *, plugin_manager: Any = None, **_kwargs: Any) -> UISpec:
    plugins = await _safe_list_plugins(plugin_manager)
    manager_available = plugin_manager is not None

    items: list[Component] = [_plugin_card(p) for p in plugins]

    children: list[Component] = [
        Component(type="heading", id="h", props={"value": "설치된 플러그인", "level": 2}),
        Component(type="text", id="count", props={"value": f"총 {len(plugins)}개"}),
    ]

    if not manager_available:
        children.append(
            Component(
                type="text",
                id="no-manager",
                props={"value": "플러그인 매니저를 사용할 수 없습니다."},
            )
        )
    elif not plugins:
        children.append(
            Component(
                type="text",
                id="empty",
                props={"value": "설치된 플러그인이 없습니다."},
            )
        )
    else:
        children.append(
            Component(
                type="stack",
                id="list",
                props={"gap": "sm"},
                children=items,
            )
        )

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="plugins",
            props={"title": "플러그인"},
            children=children,
        ),
    )


def _plugin_card(p: dict) -> Component:
    name = p.get("name", "unknown")
    version = p.get("version", "")
    enabled = bool(p.get("enabled", False))
    desc = p.get("description", "")
    return Component(
        type="list",
        id=f"plug-{name}",
        props={"variant": "plugin"},
        children=[
            Component(
                type="heading",
                id=f"name-{name}",
                props={"value": f"{name} v{version}", "level": 4},
            ),
            Component(
                type="badge",
                id=f"status-{name}",
                props={
                    "value": "활성" if enabled else "비활성",
                    "tone": "success" if enabled else "neutral",
                },
            ),
            Component(type="text", id=f"desc-{name}", props={"value": desc}),
            Component(
                type="stack",
                id=f"actions-{name}",
                props={"gap": "sm"},
                children=[
                    Component(
                        type="button",
                        id=f"toggle-{name}",
                        props={
                            "label": "비활성화" if enabled else "활성화",
                            "variant": "ghost",
                            "action": {
                                "kind": "intervention",
                                "category": "plugin",
                                "operation": "disable" if enabled else "enable",
                                "plugin": name,
                            },
                        },
                    ),
                    Component(
                        type="button",
                        id=f"uninstall-{name}",
                        props={
                            "label": "제거",
                            "variant": "ghost",
                            "action": {
                                "kind": "intervention",
                                "category": "plugin",
                                "operation": "uninstall",
                                "plugin": name,
                            },
                        },
                    ),
                ],
            ),
        ],
    )


async def _safe_list_plugins(manager: Any) -> list[dict]:
    if manager is None:
        return []
    try:
        # 1) list_plugins() — most common convention
        if hasattr(manager, "list_plugins"):
            result = manager.list_plugins()
            if hasattr(result, "__await__"):
                result = await result
            return _normalize_collection(result)

        # 2) loaded_plugins property (actual BreadMind PluginManager)
        if hasattr(manager, "loaded_plugins"):
            result = manager.loaded_plugins
            return _normalize_collection(result)

        # 3) plugins attribute/property
        if hasattr(manager, "plugins"):
            result = manager.plugins
            return _normalize_collection(result)
    except Exception:
        return []
    return []


def _normalize_collection(result: Any) -> list[dict]:
    if result is None:
        return []
    if isinstance(result, dict):
        return [_normalize(k, v) for k, v in result.items()]
    try:
        return [_normalize(None, p) for p in result]
    except TypeError:
        return []


def _normalize(key: Any, p: Any) -> dict:
    if isinstance(p, dict):
        out = dict(p)
        if "name" not in out and key is not None:
            out["name"] = str(key)
        out.setdefault("name", "unknown")
        out.setdefault("version", "")
        out.setdefault("description", "")
        out.setdefault("enabled", False)
        return out
    return {
        "name": getattr(p, "name", str(key) if key is not None else "unknown"),
        "version": getattr(p, "version", ""),
        "description": getattr(p, "description", ""),
        "enabled": getattr(p, "enabled", True),
    }
