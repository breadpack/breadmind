"""Tests for macro recording, playback, and tool definitions."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.browser_macro import BrowserMacro, MacroStep
from breadmind.tools.browser_macro_store import MacroStore


@pytest.fixture
def store():
    s = MacroStore()
    s.add(BrowserMacro(
        id="m1", name="Login",
        steps=[
            MacroStep(tool="browser_navigate", params={"url": "https://app.com/login"}),
            MacroStep(tool="browser_action", params={"action": "fill", "selector": "#email", "value": "user@x.com"}),
            MacroStep(tool="browser_action", params={"action": "click", "text": "Sign In"}),
        ],
        description="Auto login",
    ))
    return s


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.navigate = AsyncMock(return_value="Navigated to: https://app.com/login")
    engine.do_action = AsyncMock(return_value="Clicked: Sign In")
    engine.screenshot = AsyncMock(return_value="Screenshot captured")
    return engine


@pytest.fixture
def tools(store, mock_engine):
    from breadmind.tools.browser_macro_tools import MacroTools
    return MacroTools(store, mock_engine)


async def test_play_macro(tools, mock_engine):
    result = await tools.play(macro_id="m1")
    assert "Login" in result
    assert mock_engine.navigate.call_count == 1
    assert mock_engine.do_action.call_count == 2


async def test_play_macro_not_found(tools):
    result = await tools.play(macro_id="nonexistent")
    assert "[error]" in result


async def test_list_macros(tools):
    result = await tools.list_macros()
    assert "Login" in result
    assert "m1" in result


async def test_list_macros_empty():
    from breadmind.tools.browser_macro_tools import MacroTools
    tools = MacroTools(MacroStore(), MagicMock())
    result = await tools.list_macros()
    assert "No macros" in result


async def test_record_start_and_stop(tools):
    # Start recording
    result = await tools.record(action="start", name="New Macro")
    assert "Recording started" in result
    assert tools._recorder is not None

    # Record some actions
    tools.record_step("browser_navigate", {"url": "https://x.com"})
    tools.record_step("browser_action", {"action": "click", "selector": "#btn"})

    # Stop recording
    result = await tools.record(action="stop")
    assert "saved" in result.lower() or "Recorded" in result
    assert tools._recorder is None
    # Macro should be in store
    macros = tools._store.list_all()
    assert len(macros) == 2  # original + new one


async def test_manage_delete(tools):
    result = await tools.manage(action="delete", macro_id="m1")
    assert "Deleted" in result or "deleted" in result
    assert tools._store.get("m1") is None


async def test_get_tool_functions(tools):
    funcs = tools.get_tool_functions()
    names = [f.__name__ for f in funcs]
    assert "browser_macro_record" in names
    assert "browser_macro_play" in names
    assert "browser_macro_list" in names
    assert "browser_macro_manage" in names
    assert len(funcs) == 4
