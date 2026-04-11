"""UISpecProjector: build views on demand from current DB state.

The projector is the central dispatcher for the Server-Driven UI. It receives a
view request, instantiates the appropriate view builder, injects optional
runtime dependencies (settings store, plugin manager, etc.), and wraps the
resulting page with a global navigation shell so every view shares the same
top-level chrome.
"""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import UISpec, Component
from breadmind.sdui.views import (
    chat_view,
    flow_list_view,
    flow_detail_view,
    monitoring_view,
    settings_view,
    plugins_view,
    browser_view,
    connections_view,
    coding_jobs_view,
)


# Navigation menu definition. Each entry is (view_key, label, icon).
NAV_ITEMS = [
    ("chat_view", "Chat", "💬"),
    ("flow_list_view", "Flows", "🌊"),
    ("coding_jobs_view", "Coding", "💻"),
    ("browser_view", "Browser", "🌐"),
    ("connections_view", "Connections", "🔌"),
    ("monitoring_view", "Monitoring", "📊"),
    ("plugins_view", "Plugins", "🧩"),
    ("settings_view", "Settings", "⚙️"),
]


class UISpecProjector:
    def __init__(
        self,
        db: Any,
        bus: Any,
        *,
        working_memory: Any = None,
        settings_store: Any = None,
        plugin_manager: Any = None,
        browser_engine: Any = None,
        messenger_router: Any = None,
        job_tracker: Any = None,
    ) -> None:
        self._db = db
        self._bus = bus
        self._working_memory = working_memory
        self._settings_store = settings_store
        self._plugin_manager = plugin_manager
        self._browser_engine = browser_engine
        self._messenger_router = messenger_router
        self._job_tracker = job_tracker

    async def build_view(self, view_key: str, **params: Any) -> UISpec:
        spec = await self._build_inner(view_key, **params)
        return _wrap_with_shell(spec, active_view=view_key)

    async def _build_inner(self, view_key: str, **params: Any) -> UISpec:
        if view_key == "chat_view":
            params.setdefault("working_memory", self._working_memory)
            return await chat_view.build(self._db, **params)
        if view_key == "flow_list_view":
            return await flow_list_view.build(self._db, **params)
        if view_key == "flow_detail_view":
            return await flow_detail_view.build(self._db, **params)
        if view_key == "monitoring_view":
            return await monitoring_view.build(self._db, **params)
        if view_key == "settings_view":
            params.setdefault("settings_store", self._settings_store)
            return await settings_view.build(self._db, **params)
        if view_key == "plugins_view":
            params.setdefault("plugin_manager", self._plugin_manager)
            return await plugins_view.build(self._db, **params)
        if view_key == "browser_view":
            params.setdefault("browser_engine", self._browser_engine)
            return await browser_view.build(self._db, **params)
        if view_key == "connections_view":
            params.setdefault("messenger_router", self._messenger_router)
            return await connections_view.build(self._db, **params)
        if view_key == "coding_jobs_view":
            params.setdefault("job_tracker", self._job_tracker)
            return await coding_jobs_view.build(self._db, **params)
        raise ValueError(f"unknown view_key: {view_key}")


def _wrap_with_shell(spec: UISpec, *, active_view: str) -> UISpec:
    """Prepend a navigation bar to the spec's root page so every view shares
    the same top-level chrome. The original page becomes the second child of
    a synthetic outer ``page`` (so we can stack nav + content)."""
    nav_buttons = [
        Component(
            type="button",
            id=f"nav-{key}",
            props={
                "label": f"{icon} {label}",
                "variant": "primary" if key == active_view else "ghost",
                "action": {
                    "kind": "view_request",
                    "view_key": key,
                    "params": {},
                },
            },
        )
        for key, label, icon in NAV_ITEMS
    ]
    nav_bar = Component(
        type="stack",
        id="nav-bar",
        props={"gap": "sm", "variant": "nav"},
        children=nav_buttons,
    )

    # Take the inner page's children and put them inside a content stack.
    inner_root = spec.root
    content = Component(
        type="stack",
        id="page-content",
        props={"gap": "md"},
        children=inner_root.children,
    )

    # Wrap in a new outer page that contains nav + content.
    wrapped = Component(
        type="page",
        id=f"shell-{inner_root.id}",
        props={"title": inner_root.props.get("title", "BreadMind")},
        children=[nav_bar, content],
    )

    return UISpec(
        schema_version=spec.schema_version,
        root=wrapped,
        bindings=spec.bindings,
    )
