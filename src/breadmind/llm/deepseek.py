"""DeepSeek provider (DeepSeek-V3, DeepSeek-R1, etc.)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek API provider."""

    PROVIDER_NAME = "deepseek"
    BASE_URL = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True

    def _extra_chat_kwargs(self, kwargs: dict) -> dict:
        """Add reasoning_effort for R1 models when think_budget is set."""
        # DeepSeek R1 supports reasoning_effort parameter
        model = kwargs.get("model", "")
        if "r1" in model.lower() or "reasoner" in model.lower():
            # Use a higher max_tokens for reasoning models
            kwargs["max_tokens"] = 8192
        return kwargs
