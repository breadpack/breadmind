"""Tests for chat frontend file structure and DOM requirements."""
from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "breadmind" / "web" / "static"


class TestChatFiles:
    """Verify that the required chat frontend files exist."""

    def test_chat_js_exists(self):
        path = STATIC_DIR / "js" / "chat.js"
        assert path.exists(), f"chat.js not found at {path}"

    def test_chat_css_exists(self):
        path = STATIC_DIR / "css" / "chat.css"
        assert path.exists(), f"chat.css not found at {path}"

    def test_chat_js_not_empty(self):
        path = STATIC_DIR / "js" / "chat.js"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, "chat.js is too small"

    def test_chat_css_not_empty(self):
        path = STATIC_DIR / "css" / "chat.css"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, "chat.css is too small"


class TestIndexHtmlIntegration:
    """Verify index.html includes chat assets and required DOM elements."""

    def _read_index(self) -> str:
        path = STATIC_DIR / "index.html"
        return path.read_text(encoding="utf-8")

    def test_chat_js_script_tag(self):
        html = self._read_index()
        assert 'src="/static/js/chat.js"' in html, "chat.js script tag missing"

    def test_chat_css_link_tag(self):
        html = self._read_index()
        assert 'href="/static/css/chat.css"' in html, "chat.css link tag missing"

    def test_messages_container_exists(self):
        html = self._read_index()
        assert 'id="messages"' in html, "messages container missing"

    def test_input_area_exists(self):
        html = self._read_index()
        assert 'id="messageInput"' in html, "message input field missing"

    def test_send_button_exists(self):
        html = self._read_index()
        assert 'id="sendBtn"' in html, "send button missing"

    def test_status_bar_exists(self):
        html = self._read_index()
        assert 'id="statusBar"' in html, "status bar missing"

    def test_status_dot_exists(self):
        html = self._read_index()
        assert 'id="statusDot"' in html, "status dot missing"

    def test_session_list_exists(self):
        html = self._read_index()
        assert 'id="sessionList"' in html, "session list missing"


class TestChatJsStructure:
    """Verify chat.js contains required class and methods."""

    def _read_chat_js(self) -> str:
        path = STATIC_DIR / "js" / "chat.js"
        return path.read_text(encoding="utf-8")

    def test_chatapp_class_defined(self):
        js = self._read_chat_js()
        assert "class ChatApp" in js, "ChatApp class not defined"

    def test_websocket_connect(self):
        js = self._read_chat_js()
        assert "connect()" in js, "connect method missing"
        assert "WebSocket" in js, "WebSocket usage missing"

    def test_stream_event_handling(self):
        js = self._read_chat_js()
        for event_type in ["text", "tool_start", "tool_end", "done", "error"]:
            assert f"'{event_type}'" in js or f'"{event_type}"' in js, (
                f"StreamEvent type '{event_type}' not handled"
            )

    def test_markdown_rendering(self):
        js = self._read_chat_js()
        assert "renderMarkdown" in js, "renderMarkdown method missing"

    def test_reconnect_logic(self):
        js = self._read_chat_js()
        assert "reconnectAttempts" in js, "reconnect attempt tracking missing"
        assert "maxReconnectAttempts" in js, "max reconnect attempts missing"

    def test_approval_dialog(self):
        js = self._read_chat_js()
        assert "showApprovalDialog" in js, "showApprovalDialog method missing"
        assert "approval_response" in js, "approval_response WebSocket send missing"

    def test_session_management(self):
        js = self._read_chat_js()
        assert "loadSessions" in js, "loadSessions method missing"
        assert "switchSession" in js, "switchSession method missing"
        assert "newSession" in js, "newSession method missing"

    def test_global_backward_compat(self):
        """chat.js should expose global functions for inline HTML onclick handlers."""
        js = self._read_chat_js()
        for fn in ["sendMessage", "newSession", "switchSession",
                    "escapeHtml", "addMessage", "chatApproval"]:
            assert f"function {fn}" in js, (
                f"Global backward-compat function '{fn}' not defined"
            )


class TestChatCssStructure:
    """Verify chat.css contains required style rules."""

    def _read_chat_css(self) -> str:
        path = STATIC_DIR / "css" / "chat.css"
        return path.read_text(encoding="utf-8")

    def test_typing_indicator_styles(self):
        css = self._read_chat_css()
        assert ".typing-indicator" in css, "typing indicator styles missing"

    def test_typing_animation(self):
        css = self._read_chat_css()
        assert "typing-bounce" in css, "typing bounce animation missing"

    def test_tool_indicator_styles(self):
        css = self._read_chat_css()
        assert ".tool-indicator" in css, "tool indicator styles missing"

    def test_tool_result_styles(self):
        css = self._read_chat_css()
        assert ".tool-result" in css, "tool result (collapsible) styles missing"

    def test_spinner_animation(self):
        css = self._read_chat_css()
        assert "@keyframes spin" in css, "spinner animation missing"

    def test_approval_dialog_styles(self):
        css = self._read_chat_css()
        assert ".approval-dialog" in css, "approval dialog styles missing"

    def test_status_bar_styles(self):
        css = self._read_chat_css()
        assert ".status-bar" in css, "status bar styles missing"

    def test_streaming_cursor(self):
        css = self._read_chat_css()
        assert ".streaming" in css, "streaming bubble styles missing"
        assert "cursor-blink" in css, "cursor blink animation missing"

    def test_mobile_responsive(self):
        css = self._read_chat_css()
        assert "@media" in css, "responsive media query missing"
        assert "768px" in css, "768px breakpoint missing"

    def test_code_block_styles(self):
        css = self._read_chat_css()
        assert "pre code" in css or "pre" in css, "code block styles missing"
