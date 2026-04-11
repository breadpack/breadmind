"""Groq provider (ultra-fast inference for open models)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    """Groq API provider (fast inference)."""

    PROVIDER_NAME = "groq"
    BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True
