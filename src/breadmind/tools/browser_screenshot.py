"""Screenshot extraction from tool results — converts base64 tags to Attachments."""
from __future__ import annotations

import re
from breadmind.llm.base import Attachment

_SCREENSHOT_RE = re.compile(
    r"\[screenshot_base64\](.*?)\[/screenshot_base64\]", re.DOTALL
)
_PDF_RE = re.compile(
    r"\[pdf_base64\](.*?)\[/pdf_base64\]", re.DOTALL
)

_BROWSER_TOOL_PREFIXES = ("browser_", "browser")


def is_browser_tool(tool_name: str) -> bool:
    """Check if a tool name belongs to the browser engine."""
    return tool_name.startswith(_BROWSER_TOOL_PREFIXES)


def process_tool_result(content: str) -> tuple[str, list[Attachment]]:
    """Extract screenshot/PDF tags from tool result, return cleaned text + attachments."""
    attachments: list[Attachment] = []

    for match in _SCREENSHOT_RE.finditer(content):
        data = match.group(1).strip()
        attachments.append(Attachment(type="image", data=data, media_type="image/png"))

    for match in _PDF_RE.finditer(content):
        data = match.group(1).strip()
        attachments.append(Attachment(type="file", data=data, media_type="application/pdf"))

    cleaned = _SCREENSHOT_RE.sub("", content)
    cleaned = _PDF_RE.sub("", cleaned)
    cleaned = cleaned.strip()

    return cleaned, attachments
