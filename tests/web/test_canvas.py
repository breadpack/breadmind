"""Tests for canvas (A2UI) foundation."""
from __future__ import annotations

from breadmind.web.canvas import CanvasManager


async def test_create_surface():
    mgr = CanvasManager()
    surface = mgr.create_surface("session1", content="<h1>Hello</h1>")
    assert surface.id.startswith("canvas_")
    assert surface.session_id == "session1"
    assert surface.content == "<h1>Hello</h1>"


async def test_update_surface():
    mgr = CanvasManager()
    surface = mgr.create_surface("session1")
    updated = mgr.update_surface(surface.id, content="Updated")
    assert updated is not None
    assert updated.content == "Updated"
    # Update nonexistent
    assert mgr.update_surface("nonexistent", content="x") is None


async def test_delete_surface():
    mgr = CanvasManager()
    surface = mgr.create_surface("session1")
    assert mgr.delete_surface(surface.id) is True
    assert mgr.delete_surface(surface.id) is False
    assert mgr.get_surface(surface.id) is None


async def test_list_by_session():
    mgr = CanvasManager()
    mgr.create_surface("session1", content="a")
    mgr.create_surface("session2", content="b")
    mgr.create_surface("session1", content="c")
    assert len(mgr.list_surfaces("session1")) == 2
    assert len(mgr.list_surfaces("session2")) == 1
    assert len(mgr.list_surfaces()) == 3


async def test_render_surface():
    mgr = CanvasManager()
    surface = mgr.create_surface("session1", content="<p>Test</p>")
    html = mgr.render_surface(surface.id)
    assert "<p>Test</p>" in html
    assert "BreadMind Canvas" in html
    # Nonexistent returns empty
    assert mgr.render_surface("nonexistent") == ""
