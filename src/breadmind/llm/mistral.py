"""Mistral AI provider (Mistral Large, Medium, Small, etc.)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class MistralProvider(OpenAICompatibleProvider):
    """Mistral AI API provider."""

    PROVIDER_NAME = "mistral"
    BASE_URL = "https://api.mistral.ai/v1"
    DEFAULT_MODEL = "mistral-large-latest"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True
