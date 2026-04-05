"""Tests for breadmind.cli.ui -- ConsoleUI with rich and plain-text fallback."""

from __future__ import annotations

import io
import sys
from unittest.mock import patch, MagicMock

import pytest

from breadmind.cli.ui import ConsoleUI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_plain(method_name: str, *args, **kwargs) -> str:
    """Call a ConsoleUI method in plain mode and capture stdout."""
    ui = ConsoleUI(force_plain=True)
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        getattr(ui, method_name)(*args, **kwargs)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Basic message methods
# ---------------------------------------------------------------------------

class TestMessageMethods:
    def test_info_plain(self):
        output = _capture_plain("info", "hello world")
        assert "[i]" in output
        assert "hello world" in output

    def test_success_plain(self):
        output = _capture_plain("success", "all good")
        assert "[ok]" in output
        assert "all good" in output

    def test_warning_plain(self):
        output = _capture_plain("warning", "be careful")
        assert "[!]" in output
        assert "be careful" in output

    def test_error_plain(self):
        output = _capture_plain("error", "something broke")
        assert "[x]" in output
        assert "something broke" in output

    def test_info_rich(self):
        """Ensure info() runs without error when rich is available."""
        ui = ConsoleUI()
        # Should not raise regardless of rich availability
        buf = io.StringIO()
        if ui.is_rich:
            ui._console.file = buf
        else:
            with patch("sys.stdout", buf):
                pass
        ui.info("test message")


# ---------------------------------------------------------------------------
# Fallback without rich
# ---------------------------------------------------------------------------

class TestFallbackWithoutRich:
    def test_force_plain_mode(self):
        ui = ConsoleUI(force_plain=True)
        assert not ui.is_rich

    def test_all_methods_work_in_plain_mode(self):
        """All public methods should work without raising in plain mode."""
        ui = ConsoleUI(force_plain=True)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            ui.info("info")
            ui.success("success")
            ui.warning("warning")
            ui.error("error")
            ui.panel("title", "content")
            ui.table(["A", "B"], [["1", "2"]])
            ui.markdown("# heading")
        output = buf.getvalue()
        assert "info" in output
        assert "success" in output
        assert "title" in output
        assert "heading" in output


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------

class TestSpinner:
    def test_spinner_plain(self):
        ui = ConsoleUI(force_plain=True)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            with ui.spinner("loading"):
                pass  # work happens here
        output = buf.getvalue()
        assert "loading" in output
        assert "done" in output

    def test_spinner_context_manager_returns(self):
        """Spinner should be usable as a context manager and not swallow exceptions."""
        ui = ConsoleUI(force_plain=True)
        with pytest.raises(ValueError, match="test"):
            with patch("sys.stdout", io.StringIO()):
                with ui.spinner("work"):
                    raise ValueError("test")


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

class TestTable:
    def test_table_plain_output(self):
        output = _capture_plain("table", ["Name", "Value"], [["a", "1"], ["bb", "22"]])
        assert "Name" in output
        assert "Value" in output
        assert "a" in output
        assert "22" in output

    def test_table_empty_rows(self):
        output = _capture_plain("table", ["H1", "H2"], [])
        assert "H1" in output


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class TestPanel:
    def test_panel_plain(self):
        output = _capture_plain("panel", "My Title", "Some content here")
        assert "My Title" in output
        assert "Some content here" in output


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

class TestPrompt:
    def test_prompt_plain_returns_input(self):
        ui = ConsoleUI(force_plain=True)
        with patch("builtins.input", return_value="hello"):
            result = ui.prompt("Enter value")
        assert result == "hello"

    def test_prompt_plain_default(self):
        ui = ConsoleUI(force_plain=True)
        with patch("builtins.input", return_value=""):
            result = ui.prompt("Enter value", default="fallback")
        assert result == "fallback"

    def test_prompt_plain_override_default(self):
        ui = ConsoleUI(force_plain=True)
        with patch("builtins.input", return_value="custom"):
            result = ui.prompt("Enter value", default="fallback")
        assert result == "custom"


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

class TestConfirm:
    @pytest.mark.parametrize("answer,expected", [
        ("y", True),
        ("yes", True),
        ("Y", True),
        ("YES", True),
        ("n", False),
        ("no", False),
        ("", False),
        ("maybe", False),
    ])
    def test_confirm_plain(self, answer: str, expected: bool):
        ui = ConsoleUI(force_plain=True)
        with patch("builtins.input", return_value=answer):
            result = ui.confirm("Continue?")
        assert result is expected


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

class TestMarkdown:
    def test_markdown_plain(self):
        output = _capture_plain("markdown", "# Hello\nSome **bold** text")
        assert "Hello" in output
        assert "bold" in output

    def test_markdown_renders_without_error(self):
        """Markdown should work in both modes without raising."""
        ui = ConsoleUI(force_plain=True)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            ui.markdown("- item 1\n- item 2")
        assert "item 1" in buf.getvalue()
