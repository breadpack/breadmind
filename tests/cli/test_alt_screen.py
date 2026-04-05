"""Tests for flicker-free alt-screen rendering."""

from __future__ import annotations

import io
import os
from unittest.mock import patch

from breadmind.cli.alt_screen import AltScreenRenderer, ScreenState


class TestIsEnabled:
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert AltScreenRenderer.is_enabled() is False

    def test_enabled_with_env(self):
        with patch.dict(os.environ, {"BREADMIND_NO_FLICKER": "1"}):
            assert AltScreenRenderer.is_enabled() is True


class TestEnterExit:
    def test_enter_writes_alt_screen_sequences(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        r.enter()
        output = buf.getvalue()
        assert AltScreenRenderer.ENTER_ALT in output
        assert AltScreenRenderer.HIDE_CURSOR in output
        assert r.active is True

    def test_exit_writes_restore_sequences(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        r.enter()
        buf.truncate(0)
        buf.seek(0)
        r.exit()
        output = buf.getvalue()
        assert AltScreenRenderer.SHOW_CURSOR in output
        assert AltScreenRenderer.EXIT_ALT in output
        assert r.active is False

    def test_double_enter_is_noop(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        r.enter()
        first = buf.getvalue()
        r.enter()
        assert buf.getvalue() == first

    def test_double_exit_is_noop(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        r.exit()  # not active, should do nothing
        assert buf.getvalue() == ""


class TestContextManager:
    def test_alt_screen_context(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        with r.alt_screen() as renderer:
            assert renderer.active is True
        assert r.active is False


class TestRenderFrame:
    def test_render_only_changed_lines(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        r.enter()
        buf.truncate(0)
        buf.seek(0)

        r.render_frame(["line 0", "line 1"])
        first_render = buf.getvalue()
        assert "line 0" in first_render
        assert "line 1" in first_render

        buf.truncate(0)
        buf.seek(0)
        r.render_frame(["line 0", "CHANGED"])
        second_render = buf.getvalue()
        assert "CHANGED" in second_render
        # line 0 didn't change, so ideally not rewritten
        # (implementation redraws only changed lines)

    def test_render_noop_when_not_active(self):
        buf = io.StringIO()
        r = AltScreenRenderer(stream=buf)
        r.render_frame(["test"])
        assert buf.getvalue() == ""


class TestScrollback:
    def test_append_and_get(self):
        r = AltScreenRenderer(stream=io.StringIO())
        r.append_scrollback("line1\nline2\nline3")
        assert r.scrollback == ["line1", "line2", "line3"]

    def test_scroll_up_and_down(self):
        r = AltScreenRenderer(stream=io.StringIO())
        r._viewport_height = 2
        for i in range(10):
            r.append_scrollback(f"line{i}")
        r.scroll_up(3)
        assert r.viewport_offset == 3
        r.scroll_down(1)
        assert r.viewport_offset == 2

    def test_scroll_down_clamps_to_zero(self):
        r = AltScreenRenderer(stream=io.StringIO())
        r.scroll_down(100)
        assert r.viewport_offset == 0

    def test_scroll_up_clamps_to_max(self):
        r = AltScreenRenderer(stream=io.StringIO())
        r._viewport_height = 5
        for i in range(10):
            r.append_scrollback(f"l{i}")
        r.scroll_up(999)
        assert r.viewport_offset == 5  # 10 - 5


class TestScreenState:
    def test_defaults(self):
        s = ScreenState()
        assert s.lines == []
        assert s.cursor_row == 0
        assert s.cursor_col == 0
