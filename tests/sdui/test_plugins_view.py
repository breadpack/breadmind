"""Tests for the plugins_view SDUI view."""
from __future__ import annotations

from breadmind.sdui.views import plugins_view


def _all_types(component):
    types = {component.type}
    for child in component.children:
        types |= _all_types(child)
    return types


def _find_text_containing(component, needle):
    found = []
    if component.type in ("text", "heading") and needle in str(
        component.props.get("value", "")
    ):
        found.append(component)
    for child in component.children:
        found.extend(_find_text_containing(child, needle))
    return found


async def test_plugins_view_renders_without_manager(test_db):
    spec = await plugins_view.build(test_db)
    assert spec.root.type == "page"
    # No manager → at minimum the heading "플러그인" should be present.
    assert _find_text_containing(spec.root, "플러그인")


async def test_plugins_view_with_fake_manager(test_db):
    class FakeManager:
        def list_plugins(self):
            return [
                {
                    "name": "core-tools",
                    "version": "0.1.0",
                    "description": "Core tools",
                    "enabled": True,
                },
                {
                    "name": "browser",
                    "version": "0.2.0",
                    "description": "Browser",
                    "enabled": False,
                },
            ]

    spec = await plugins_view.build(test_db, plugin_manager=FakeManager())
    assert _find_text_containing(spec.root, "core-tools")
    assert _find_text_containing(spec.root, "browser")
    types = _all_types(spec.root)
    assert "button" in types
    assert "badge" in types


async def test_plugins_view_with_broken_manager(test_db):
    class Broken:
        def list_plugins(self):
            raise RuntimeError("oops")

    spec = await plugins_view.build(test_db, plugin_manager=Broken())
    # Must not raise
    assert spec.root.type == "page"
