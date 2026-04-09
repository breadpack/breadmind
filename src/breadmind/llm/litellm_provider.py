"""LiteLLM provider — proxy or library mode.

Two modes of operation:
  1. Library mode: import litellm directly (requires `litellm` package)
  2. Proxy mode: use OpenAI client pointed at a LiteLLM proxy URL

The proxy mode always works (uses openai SDK). Library mode requires
the litellm package to be installed.
"""

from __future__ import annotations

import logging

from .openai_compat import OpenAICompatibleProvider
from .base import (
    LLMMessage,
    LLMResponse,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

try:
    import litellm as _litellm
    _HAS_LITELLM = True
except ImportError:
    _litellm = None  # type: ignore[assignment]
    _HAS_LITELLM = False


class LiteLLMProvider(OpenAICompatibleProvider):
    """LiteLLM provider — library or proxy mode."""

    PROVIDER_NAME = "litellm"
    BASE_URL = "http://localhost:4000/v1"  # default proxy URL
    DEFAULT_MODEL = "gpt-4o"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True

    def __init__(
        self,
        api_key: str = "sk-litellm",
        default_model: str | None = None,
        max_retries: int = 3,
        *,
        proxy_url: str | None = None,
        use_library: bool = False,
        **kw,
    ):
        self._use_library = use_library and _HAS_LITELLM
        if proxy_url:
            kw["base_url"] = proxy_url
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            max_retries=max_retries,
            **kw,
        )

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        if self._use_library and _HAS_LITELLM:
            return await self._chat_via_library(messages, tools, model)
        # Proxy mode: use the parent OpenAI-compatible implementation
        return await super().chat(messages, tools, model, think_budget=think_budget)

    async def _chat_via_library(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """Use litellm library directly."""
        api_messages = self._convert_messages(messages)
        kwargs: dict = {
            "model": model or self._default_model,
            "messages": api_messages,
            "max_tokens": 4096,
        }
        if tools and self.SUPPORTS_TOOL_CALLS:
            kwargs["tools"] = self._convert_tools(tools)

        response = await _litellm.acompletion(**kwargs)  # type: ignore[union-attr]
        return self._parse_response(response)

    async def health_check(self) -> bool:
        if self._use_library:
            return _HAS_LITELLM
        return await super().health_check()
