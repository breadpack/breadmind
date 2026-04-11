"""OpenRouter provider (300+ models via unified API)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter API provider (routes to 300+ models)."""

    PROVIDER_NAME = "openrouter"
    BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "openai/gpt-4o"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True

    def __init__(
        self,
        api_key: str,
        default_model: str | None = None,
        max_retries: int = 3,
        *,
        app_title: str = "BreadMind",
        site_url: str = "",
        **kw,
    ):
        self._app_title = app_title
        self._site_url = site_url
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            max_retries=max_retries,
            **kw,
        )

    def _extra_default_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"X-Title": self._app_title}
        if self._site_url:
            headers["HTTP-Referer"] = self._site_url
        return headers
