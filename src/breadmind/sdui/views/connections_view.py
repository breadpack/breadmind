"""Connections view: messenger platforms grid."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import Component, UISpec


# Platform metadata (icons + display names) — fallback when router unavailable.
PLATFORM_META: dict[str, dict[str, str]] = {
    "slack": {"name": "Slack", "icon": "💬"},
    "discord": {"name": "Discord", "icon": "🎮"},
    "telegram": {"name": "Telegram", "icon": "✈️"},
    "whatsapp": {"name": "WhatsApp", "icon": "📱"},
    "gmail": {"name": "Gmail", "icon": "✉️"},
    "signal": {"name": "Signal", "icon": "🔒"},
    "teams": {"name": "Teams", "icon": "👥"},
    "line": {"name": "LINE", "icon": "🟢"},
    "matrix": {"name": "Matrix", "icon": "🔷"},
}


async def build(db: Any, *, messenger_router: Any = None, **_kwargs: Any) -> UISpec:
    """Build the Connections (messenger platforms) view."""
    platforms = await _safe_load_platforms(messenger_router)

    cards = [_platform_card(key, info) for key, info in platforms.items()]

    connected_count = sum(1 for p in platforms.values() if p.get("connected"))
    total = len(platforms)

    return UISpec(
        schema_version=1,
        root=Component(
            type="page",
            id="connections",
            props={"title": "연결"},
            children=[
                Component(
                    type="heading",
                    id="h",
                    props={"value": "메신저 연결", "level": 2},
                ),
                Component(
                    type="text",
                    id="desc",
                    props={
                        "value": f"총 {total}개 플랫폼 중 {connected_count}개 연결됨",
                    },
                ),
                Component(
                    type="grid",
                    id="grid",
                    props={"cols": 3},
                    children=cards,
                ),
            ],
        ),
    )


def _platform_card(key: str, info: dict) -> Component:
    name = info.get("name", key)
    icon = info.get("icon", "🔌")
    connected = bool(info.get("connected", False))
    configured = bool(info.get("configured", False))

    if connected:
        badge_value = "연결됨"
        badge_tone = "success"
    elif configured:
        badge_value = "설정됨"
        badge_tone = "info"
    else:
        badge_value = "미연결"
        badge_tone = "neutral"

    toggle_button = Component(
        type="button",
        id=f"toggle-{key}",
        props={
            "label": "연결 끊기" if connected else "연결",
            "variant": "ghost" if connected else "primary",
            "action": {
                "kind": "intervention",
                "category": "messenger",
                "operation": "disconnect" if connected else "connect",
                "platform": key,
            },
        },
    )

    if configured:
        second_action: Component = Component(
            type="button",
            id=f"test-{key}",
            props={
                "label": "연결 테스트",
                "variant": "ghost",
                "action": {
                    "kind": "intervention",
                    "category": "messenger",
                    "operation": "test",
                    "platform": key,
                },
            },
        )
    else:
        second_action = Component(
            type="text",
            id=f"empty-{key}",
            props={"value": ""},
        )

    return Component(
        type="list",
        id=f"plat-{key}",
        props={"variant": "platform"},
        children=[
            Component(
                type="heading",
                id=f"name-{key}",
                props={"value": f"{icon} {name}", "level": 4},
            ),
            Component(
                type="badge",
                id=f"status-{key}",
                props={"value": badge_value, "tone": badge_tone},
            ),
            Component(
                type="stack",
                id=f"actions-{key}",
                props={"gap": "sm", "variant": "row"},
                children=[toggle_button, second_action],
            ),
        ],
    )


async def _safe_load_platforms(router: Any) -> dict[str, dict[str, Any]]:
    """Return mapping of platform_key → {name, icon, configured, connected}.

    Always returns all 9 known platforms. On any failure or missing router,
    falls back to default metadata with status=unknown (configured=False,
    connected=False).
    """
    base: dict[str, dict[str, Any]] = {
        key: {**meta, "configured": False, "connected": False}
        for key, meta in PLATFORM_META.items()
    }
    if router is None:
        return base

    # Probe a set of method names used across router implementations, in
    # priority order. First one that returns a dict wins.
    try:
        for attr in (
            "list_platforms",
            "get_platform_status",
            "platform_status",
            "platforms",
            "get_platforms",
        ):
            if not hasattr(router, attr):
                continue
            obj = getattr(router, attr)
            result = obj() if callable(obj) else obj
            if hasattr(result, "__await__"):
                result = await result
            if isinstance(result, dict):
                for key, info in result.items():
                    if key in base and isinstance(info, dict):
                        base[key].update(info)
                break
    except Exception:
        # Swallow any router errors — the view must always render.
        pass

    return base
