from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class GrokProvider(OpenAICompatibleProvider):
    """xAI Grok provider (OpenAI-compatible API)."""

    PROVIDER_NAME = "grok"
    BASE_URL = "https://api.x.ai/v1"
    DEFAULT_MODEL = "grok-3"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True

    async def health_check(self) -> bool:
        """Grok health check — verify API key is present."""
        try:
            return bool(self._api_key)
        except Exception:
            return False
