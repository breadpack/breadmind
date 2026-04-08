"""Tests for screenshot tag extraction and Attachment conversion."""
from __future__ import annotations

import base64


def test_extract_single_screenshot():
    from breadmind.tools.browser_screenshot import process_tool_result
    img_data = base64.b64encode(b"fake-png-data").decode()
    content = f"Screenshot captured\nURL: https://example.com\n[screenshot_base64]{img_data}[/screenshot_base64]"
    cleaned, attachments = process_tool_result(content)
    assert "[screenshot_base64]" not in cleaned
    assert len(attachments) == 1
    assert attachments[0].type == "image"
    assert attachments[0].data == img_data
    assert attachments[0].media_type == "image/png"


def test_extract_multiple_screenshots():
    from breadmind.tools.browser_screenshot import process_tool_result
    img1 = base64.b64encode(b"img1").decode()
    img2 = base64.b64encode(b"img2").decode()
    content = f"[screenshot_base64]{img1}[/screenshot_base64] middle [screenshot_base64]{img2}[/screenshot_base64]"
    cleaned, attachments = process_tool_result(content)
    assert len(attachments) == 2
    assert "[screenshot_base64]" not in cleaned


def test_no_screenshots():
    from breadmind.tools.browser_screenshot import process_tool_result
    content = "Navigated to https://example.com\nTitle: Example"
    cleaned, attachments = process_tool_result(content)
    assert cleaned == content
    assert len(attachments) == 0


def test_pdf_tag_extraction():
    from breadmind.tools.browser_screenshot import process_tool_result
    pdf_data = base64.b64encode(b"%PDF-fake").decode()
    content = f"PDF exported\n[pdf_base64]{pdf_data}[/pdf_base64]"
    cleaned, attachments = process_tool_result(content)
    assert "[pdf_base64]" not in cleaned
    assert len(attachments) == 1
    assert attachments[0].media_type == "application/pdf"


def test_cleaned_text_preserves_metadata():
    from breadmind.tools.browser_screenshot import process_tool_result
    img_data = base64.b64encode(b"png").decode()
    content = f"Screenshot (100 bytes)\nURL: https://x.com\nTitle: X\n[screenshot_base64]{img_data}[/screenshot_base64]"
    cleaned, _ = process_tool_result(content)
    assert "URL: https://x.com" in cleaned
    assert "Title: X" in cleaned


def test_is_browser_tool():
    from breadmind.tools.browser_screenshot import is_browser_tool
    assert is_browser_tool("browser_screenshot") is True
    assert is_browser_tool("browser_navigate") is True
    assert is_browser_tool("browser_action") is True
    assert is_browser_tool("shell_exec") is False
    assert is_browser_tool("browser") is True
