"""Input sanitization layer for BreadMind.

Provides message sanitization, HTML stripping, length enforcement,
and prompt injection detection.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Prompt injection patterns (case-insensitive)
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore previous instructions", re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE)),
    ("system prompt:", re.compile(r"system\s+prompt\s*:", re.IGNORECASE)),
    ("you are now", re.compile(r"you\s+are\s+now\b", re.IGNORECASE)),
    ("disregard above", re.compile(r"disregard\s+(the\s+)?(above|previous)", re.IGNORECASE)),
    ("new instructions", re.compile(r"new\s+instructions\s*:", re.IGNORECASE)),
    ("forget everything", re.compile(r"forget\s+everything", re.IGNORECASE)),
    ("override instructions", re.compile(r"override\s+(your\s+)?instructions", re.IGNORECASE)),
    ("act as", re.compile(r"from\s+now\s+on[,\s]+act\s+as", re.IGNORECASE)),
    ("jailbreak", re.compile(r"(?:DAN|jailbreak)\s+mode", re.IGNORECASE)),
    ("ignore safety", re.compile(r"ignore\s+(all\s+)?(safety|security)\s+(rules|guidelines)", re.IGNORECASE)),
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_NULL_BYTE_RE = re.compile(r"\x00")


@dataclass
class SanitizerConfig:
    """Configuration for the input sanitizer."""

    max_message_length: int = 100_000  # ~25K tokens
    max_tool_output_length: int = 200_000
    strip_html: bool = True
    detect_prompt_injection: bool = True


class InputSanitizer:
    """Sanitizes user inputs: length limits, HTML stripping, injection detection."""

    def __init__(self, config: SanitizerConfig | None = None) -> None:
        self._config = config or SanitizerConfig()

    @property
    def config(self) -> SanitizerConfig:
        return self._config

    def sanitize_message(self, text: str) -> str:
        """Sanitize a user message.

        - Strips leading/trailing whitespace
        - Removes null bytes
        - Strips HTML tags (if configured)
        - Enforces length limit
        """
        if not text:
            return text

        # Strip whitespace
        text = text.strip()

        # Remove null bytes
        text = _NULL_BYTE_RE.sub("", text)

        # Strip HTML
        if self._config.strip_html:
            text = self.sanitize_html(text)

        # Length limit
        if len(text) > self._config.max_message_length:
            logger.warning(
                "Message truncated: %d -> %d chars",
                len(text), self._config.max_message_length,
            )
            text = text[:self._config.max_message_length]

        return text

    def sanitize_tool_args(self, args: dict) -> dict:
        """Sanitize tool call arguments recursively."""
        return self._sanitize_value(args, self._config.max_tool_output_length)

    def _sanitize_value(self, value: object, max_len: int) -> object:
        """Recursively sanitize a value."""
        if isinstance(value, str):
            result = _NULL_BYTE_RE.sub("", value)
            if self._config.strip_html:
                result = self.sanitize_html(result)
            if len(result) > max_len:
                logger.warning(
                    "Tool arg truncated: %d -> %d chars",
                    len(result), max_len,
                )
                result = result[:max_len]
            return result
        if isinstance(value, dict):
            return {k: self._sanitize_value(v, max_len) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_value(item, max_len) for item in value]
        return value

    def check_prompt_injection(self, text: str) -> tuple[bool, str]:
        """Check text for prompt injection patterns.

        Returns:
            (detected, pattern_name) - detection only, does not block.
        """
        if not self._config.detect_prompt_injection:
            return False, ""

        for name, pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                return True, name

        return False, ""

    def sanitize_html(self, text: str) -> str:
        """Remove HTML tags and escape special characters."""
        # Remove tags first, then escape remaining entities
        text = _HTML_TAG_RE.sub("", text)
        text = html.escape(text, quote=False)
        return text
