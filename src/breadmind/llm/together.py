"""Together AI provider (open-source models via API)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class TogetherProvider(OpenAICompatibleProvider):
    """Together AI API provider."""

    PROVIDER_NAME = "together"
    BASE_URL = "https://api.together.xyz/v1"
    DEFAULT_MODEL = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True
