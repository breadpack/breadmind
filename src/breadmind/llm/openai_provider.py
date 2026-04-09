"""OpenAI provider (GPT-4o, GPT-4o-mini, o1, etc.)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI API provider."""

    PROVIDER_NAME = "openai"
    BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True
