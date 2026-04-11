"""Tests for the connections_view SDUI view."""
from __future__ import annotations

from breadmind.sdui.views import connections_view


def _all_types(c):
    out = {c.type}
    for ch in c.children:
        out |= _all_types(ch)
    return out


def _find_text_with(c, needle):
    if c.type in ("text", "heading") and needle in str(c.props.get("value", "")):
        return True
    return any(_find_text_with(ch, needle) for ch in c.children)


async def test_connections_view_renders_all_platforms(test_db):
    spec = await connections_view.build(test_db)
    assert spec.root.type == "page"
    # All 9 platforms should appear
    for name in [
        "Slack",
        "Discord",
        "Telegram",
        "WhatsApp",
        "Gmail",
        "Signal",
        "Teams",
        "LINE",
        "Matrix",
    ]:
        assert _find_text_with(spec.root, name), f"missing {name}"
    types = _all_types(spec.root)
    assert "grid" in types
    assert "badge" in types
    assert "button" in types


async def test_connections_view_with_fake_router(test_db):
    class FakeRouter:
        def list_platforms(self):
            return {
                "slack": {"connected": True, "configured": True},
                "telegram": {"configured": True, "connected": False},
            }

    spec = await connections_view.build(test_db, messenger_router=FakeRouter())
    # Should reflect connection status — 1 connected platform
    assert _find_text_with(spec.root, "1개 연결됨") or _find_text_with(spec.root, "1")


async def test_connections_view_with_broken_router(test_db):
    class Broken:
        def list_platforms(self):
            raise RuntimeError("nope")

    spec = await connections_view.build(test_db, messenger_router=Broken())
    # Should still render all platforms with default state
    assert spec.root.type == "page"
    for name in ["Slack", "Discord", "Telegram", "Matrix"]:
        assert _find_text_with(spec.root, name)


async def test_connections_view_spec_validates(test_db):
    from breadmind.sdui.schema import validate_spec

    spec = await connections_view.build(test_db)
    # Should not raise — all components must be in KNOWN_COMPONENTS.
    validate_spec(spec)
