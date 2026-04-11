"""Tests for the settings_view SDUI view."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.schema import validate_spec
from breadmind.sdui.views import settings_view


def _all_types(component) -> set[str]:
    types = {component.type}
    for child in component.children:
        types |= _all_types(child)
    return types


def _find_by_id(component, node_id: str):
    if component.id == node_id:
        return component
    for child in component.children:
        found = _find_by_id(child, node_id)
        if found is not None:
            return found
    return None


class _FakeStore:
    """Minimal settings store with get_setting(key) surface."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    async def get_setting(self, key: str) -> Any:
        return self._data.get(key)


class _BrokenStore:
    async def get_setting(self, key: str) -> Any:
        raise RuntimeError("store is broken")


async def test_settings_view_renders_without_store(test_db):
    spec = await settings_view.build(test_db)
    assert spec.root.type == "page"
    assert spec.root.props.get("title") == "설정"
    types = _all_types(spec.root)
    assert "tabs" in types
    # At least some display content should be present.
    assert "kv" in types or "text" in types


async def test_settings_view_renders_all_tabs(test_db):
    spec = await settings_view.build(test_db)
    tabs = next(c for c in spec.root.children if c.type == "tabs")
    # 4 tabs: System, Safety, Timeouts, About.
    assert len(tabs.children) >= 3
    tab_ids = {c.id for c in tabs.children}
    assert "tab-system" in tab_ids
    assert "tab-safety" in tab_ids
    assert "tab-timeouts" in tab_ids
    assert "tab-about" in tab_ids


async def test_settings_view_with_failing_store(test_db):
    spec = await settings_view.build(test_db, settings_store=_BrokenStore())
    # Must not raise — placeholder content rendered instead.
    assert spec.root.type == "page"
    # System tab must still contain its kv lists with placeholder values.
    llm_kv = _find_by_id(spec.root, "tab-system-llm-kv")
    assert llm_kv is not None
    items = llm_kv.props["items"]
    assert any(item["value"] == "N/A" for item in items)


async def test_settings_view_populates_system_from_store(test_db):
    store = _FakeStore({
        "llm": {
            "default_provider": "claude",
            "default_model": "claude-3-opus",
            "tool_call_max_turns": 10,
        },
        "database": {"host": "localhost", "port": 5432, "name": "breadmind"},
        "usage": {"tokens_in": 100, "tokens_out": 200, "cost": 0.05},
        "monitoring_status": {"running": True, "rules": 3, "events_total": 42},
    })
    spec = await settings_view.build(test_db, settings_store=store)
    llm_kv = _find_by_id(spec.root, "tab-system-llm-kv")
    assert llm_kv is not None
    values = {item["key"]: item["value"] for item in llm_kv.props["items"]}
    assert values["LLM Provider"] == "claude"
    assert values["Default Model"] == "claude-3-opus"
    assert values["Tool Call Max Turns"] == "10"

    mon_kv = _find_by_id(spec.root, "tab-system-mon-kv")
    mon_values = {item["key"]: item["value"] for item in mon_kv.props["items"]}
    assert mon_values["Running"] == "예"
    assert mon_values["Rules"] == "3"


async def test_settings_view_safety_tab_lists_entries(test_db):
    store = _FakeStore({
        "safety": {
            "blacklist": {"tools": ["rm", "dd"], "paths": ["/etc"]},
            "require_approval": ["sudo"],
            "admin_users": ["alice"],
        },
    })
    spec = await settings_view.build(test_db, settings_store=store)
    bt = _find_by_id(spec.root, "tab-safety-bt")
    assert bt is not None
    assert bt.type == "list"
    texts = [c.props["value"] for c in bt.children]
    assert "rm" in texts
    assert "dd" in texts


async def test_settings_view_safety_tab_empty_lists_show_text(test_db):
    spec = await settings_view.build(test_db, settings_store=_FakeStore({}))
    # When empty, the safety list should be replaced with a text placeholder.
    empty = _find_by_id(spec.root, "tab-safety-bt-empty")
    assert empty is not None
    assert empty.type == "text"


async def test_settings_view_spec_validates(test_db):
    spec = await settings_view.build(test_db)
    # All components must be in the KNOWN_COMPONENTS registry.
    validate_spec(spec)


async def test_settings_view_with_populated_store_validates(test_db):
    store = _FakeStore({
        "llm": {"default_provider": "grok"},
        "safety": {"blacklist": {"tools": ["rm"]}},
        "timeouts_system": {"tool_call": 30},
        "retry": {"max_retries": 5},
    })
    spec = await settings_view.build(test_db, settings_store=store)
    validate_spec(spec)
