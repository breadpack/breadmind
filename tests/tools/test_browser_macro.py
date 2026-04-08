"""Tests for browser macro data models."""
from __future__ import annotations


def test_macro_step_creation():
    from breadmind.tools.browser_macro import MacroStep
    step = MacroStep(tool="browser_navigate", params={"url": "https://example.com"})
    assert step.tool == "browser_navigate"
    assert step.params["url"] == "https://example.com"


def test_macro_step_to_dict():
    from breadmind.tools.browser_macro import MacroStep
    step = MacroStep(tool="browser_action", params={"action": "click", "selector": "#btn"})
    d = step.to_dict()
    assert d["tool"] == "browser_action"
    assert d["params"]["action"] == "click"


def test_macro_step_from_dict():
    from breadmind.tools.browser_macro import MacroStep
    d = {"tool": "browser_navigate", "params": {"url": "https://x.com"}}
    step = MacroStep.from_dict(d)
    assert step.tool == "browser_navigate"
    assert step.params["url"] == "https://x.com"


def test_browser_macro_creation():
    from breadmind.tools.browser_macro import BrowserMacro, MacroStep
    macro = BrowserMacro(
        id="m1", name="Login Flow",
        steps=[
            MacroStep(tool="browser_navigate", params={"url": "https://app.com/login"}),
            MacroStep(tool="browser_action", params={"action": "fill", "selector": "#email", "value": "user@test.com"}),
            MacroStep(tool="browser_action", params={"action": "click", "text": "Sign In"}),
        ],
        description="Automated login",
        tags=["login", "auth"],
    )
    assert macro.id == "m1"
    assert len(macro.steps) == 3
    assert macro.tags == ["login", "auth"]


def test_browser_macro_to_dict():
    from breadmind.tools.browser_macro import BrowserMacro, MacroStep
    macro = BrowserMacro(
        id="m1", name="Test",
        steps=[MacroStep(tool="browser_navigate", params={"url": "https://x.com"})],
    )
    d = macro.to_dict()
    assert d["id"] == "m1"
    assert d["name"] == "Test"
    assert len(d["steps"]) == 1
    assert d["steps"][0]["tool"] == "browser_navigate"


def test_browser_macro_from_dict():
    from breadmind.tools.browser_macro import BrowserMacro
    d = {
        "id": "m2", "name": "Scrape",
        "steps": [
            {"tool": "browser_navigate", "params": {"url": "https://x.com"}},
            {"tool": "browser_screenshot", "params": {}},
        ],
        "description": "Scraping macro",
        "tags": ["scrape"],
    }
    macro = BrowserMacro.from_dict(d)
    assert macro.id == "m2"
    assert len(macro.steps) == 2
    assert macro.steps[0].tool == "browser_navigate"
    assert macro.tags == ["scrape"]


def test_browser_macro_roundtrip():
    from breadmind.tools.browser_macro import BrowserMacro, MacroStep
    original = BrowserMacro(
        id="rt", name="Roundtrip",
        steps=[
            MacroStep(tool="browser_action", params={"action": "click", "selector": "#x"}),
        ],
        description="Test roundtrip",
        tags=["test"],
    )
    restored = BrowserMacro.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.name == original.name
    assert len(restored.steps) == len(original.steps)
    assert restored.steps[0].tool == original.steps[0].tool
