"""Token counting utilities for context window management."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LLMMessage, ToolDefinition


# Regex to match CJK Unified Ideographs, Hangul, Kana, and common CJK ranges
_CJK_PATTERN = re.compile(
    r"[\u1100-\u11ff"          # Hangul Jamo
    r"\u2e80-\u9fff"           # CJK radicals, symbols, ideographs
    r"\uac00-\ud7af"           # Hangul Syllables
    r"\uf900-\ufaff"           # CJK Compatibility Ideographs
    r"\U00020000-\U0002a6df"   # CJK Extension B
    r"\U0002a700-\U0002b73f"   # CJK Extension C
    r"\U0002b740-\U0002b81f"   # CJK Extension D
    r"\U0002b820-\U0002ceaf"   # CJK Extension E
    r"\U0002ceb0-\U0002ebef"   # CJK Extension F
    r"\U00030000-\U0003134f]"  # CJK Extension G
)


class TokenCounter:
    """Estimate token counts for context window management."""

    # Rough approximation: 1 token ≈ 4 chars for English, 2 chars for CJK
    CHARS_PER_TOKEN = 4

    # Model context windows
    MODEL_LIMITS: dict[str, int] = {
        # Anthropic
        "claude-sonnet-4-6": 200_000,
        "claude-haiku-4-5": 200_000,
        "claude-opus-4-6": 1_000_000,
        # OpenAI
        "gpt-4o": 128_000,
        "gpt-4o-mini": 128_000,
        "o1": 200_000,
        "o1-mini": 128_000,
        "o3-mini": 200_000,
        # xAI Grok
        "grok-3": 131_072,
        "grok-3-mini": 131_072,
        # Google Gemini
        "gemini-2.5-flash": 1_048_576,
        "gemini-2.5-pro": 1_048_576,
        # DeepSeek
        "deepseek-chat": 64_000,
        "deepseek-reasoner": 64_000,
        # Mistral
        "mistral-large-latest": 128_000,
        "mistral-medium-latest": 128_000,
        "mistral-small-latest": 128_000,
        "codestral-latest": 256_000,
        # Together / Meta Llama
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": 131_072,
        # Groq
        "llama-3.3-70b-versatile": 128_000,
        "llama-3.1-8b-instant": 131_072,
        "mixtral-8x7b-32768": 32_768,
        # AWS Bedrock
        "anthropic.claude-sonnet-4-6-20250514-v1:0": 200_000,
        "amazon.nova-pro-v1:0": 300_000,
        "meta.llama3-1-70b-instruct-v1:0": 128_000,
    }

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count from text.

        CJK characters are counted as roughly 1 token per 2 characters,
        while other characters use 1 token per 4 characters.
        """
        if not text:
            return 0

        cjk_chars = len(_CJK_PATTERN.findall(text))
        non_cjk_chars = len(text) - cjk_chars

        cjk_tokens = cjk_chars / 2
        non_cjk_tokens = non_cjk_chars / TokenCounter.CHARS_PER_TOKEN

        return max(1, int(cjk_tokens + non_cjk_tokens))

    @staticmethod
    def estimate_messages_tokens(messages: list[LLMMessage]) -> int:
        """Estimate total tokens for a message list."""
        total = 0
        for msg in messages:
            if msg.content:
                total += TokenCounter.estimate_tokens(msg.content)
            # Each message has a small overhead for role, formatting
            total += 4
            # Tool calls add tokens too
            for tc in msg.tool_calls:
                total += TokenCounter.estimate_tokens(tc.name)
                total += TokenCounter.estimate_tokens(json.dumps(tc.arguments))
        return total

    @staticmethod
    def estimate_tools_tokens(tools: list[ToolDefinition]) -> int:
        """Estimate tokens for tool definitions."""
        total = 0
        for tool in tools:
            total += TokenCounter.estimate_tokens(tool.name)
            total += TokenCounter.estimate_tokens(tool.description)
            total += TokenCounter.estimate_tokens(json.dumps(tool.parameters))
        return total

    @classmethod
    def get_model_limit(cls, model: str) -> int:
        """Get context window size for a model.

        Returns the limit for exact model name match, or a default of 200,000
        if the model is not recognized.
        """
        return cls.MODEL_LIMITS.get(model, 200_000)

    @classmethod
    def fits_in_context(
        cls,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None,
        model: str,
        reserve: int = 4096,
    ) -> bool:
        """Check if messages + tools fit within model's context window."""
        total = cls.estimate_messages_tokens(messages)
        if tools:
            total += cls.estimate_tools_tokens(tools)
        limit = cls.get_model_limit(model)
        return total + reserve <= limit

    @classmethod
    def trim_messages_to_fit(
        cls,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None,
        model: str,
        reserve: int = 4096,
    ) -> list[LLMMessage]:
        """Trim oldest non-system messages to fit context window.

        Always keep: first system message, last user message.
        Remove from oldest to newest until it fits.
        """
        if cls.fits_in_context(messages, tools, model, reserve):
            return list(messages)

        # Separate system messages at start and the last message
        first_system: list[LLMMessage] = []
        if messages and messages[0].role == "system":
            first_system = [messages[0]]
            middle = list(messages[1:-1]) if len(messages) > 2 else []
            last = [messages[-1]] if len(messages) > 1 else []
        else:
            middle = list(messages[:-1]) if len(messages) > 1 else []
            last = [messages[-1]] if messages else []

        # Remove from oldest (front of middle) until it fits
        while middle:
            candidate = first_system + middle + last
            if cls.fits_in_context(candidate, tools, model, reserve):
                return candidate
            middle.pop(0)

        return first_system + last
