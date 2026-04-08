"""Tests for BrowserMacroStore."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.browser_macro import BrowserMacro, MacroStep


def _make_macro(id: str, name: str) -> BrowserMacro:
    return BrowserMacro(
        id=id, name=name,
        steps=[MacroStep(tool="browser_navigate", params={"url": "https://x.com"})],
    )


def test_add_and_get():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    m = _make_macro("m1", "Test")
    store.add(m)
    assert store.get("m1") is m
    assert store.get("nonexistent") is None


def test_get_by_name():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "Login Flow"))
    assert store.get_by_name("Login Flow") is not None
    assert store.get_by_name("Missing") is None


def test_list_all():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "A"))
    store.add(_make_macro("m2", "B"))
    macros = store.list_all()
    assert len(macros) == 2


def test_remove():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "Test"))
    assert store.remove("m1") is True
    assert store.get("m1") is None
    assert store.remove("m1") is False


def test_update():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "Old Name"))
    updated = _make_macro("m1", "New Name")
    store.update(updated)
    assert store.get("m1").name == "New Name"


async def test_save_to_db():
    from breadmind.tools.browser_macro_store import MacroStore
    db = AsyncMock()
    db.set_setting = AsyncMock()
    store = MacroStore()
    store.add(_make_macro("m1", "Test"))
    await store.save(db)
    db.set_setting.assert_called_once()
    args = db.set_setting.call_args[0]
    assert args[0] == "browser_macros"


async def test_load_from_db():
    from breadmind.tools.browser_macro_store import MacroStore
    db = AsyncMock()
    db.get_setting = AsyncMock(return_value=[
        {"id": "m1", "name": "Loaded", "steps": [{"tool": "browser_navigate", "params": {"url": "https://x.com"}}]},
    ])
    store = MacroStore()
    await store.load(db)
    assert len(store.list_all()) == 1
    assert store.get("m1").name == "Loaded"


async def test_load_empty_db():
    from breadmind.tools.browser_macro_store import MacroStore
    db = AsyncMock()
    db.get_setting = AsyncMock(return_value=None)
    store = MacroStore()
    await store.load(db)
    assert len(store.list_all()) == 0
