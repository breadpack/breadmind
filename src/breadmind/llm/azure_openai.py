"""Azure OpenAI provider."""

from __future__ import annotations

import openai
from .openai_compat import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI Service provider."""

    PROVIDER_NAME = "azure_openai"
    BASE_URL = ""  # set per-deployment
    DEFAULT_MODEL = "gpt-4o"
    SUPPORTS_STREAMING = True
    SUPPORTS_TOOL_CALLS = True

    def __init__(
        self,
        api_key: str,
        default_model: str | None = None,
        max_retries: int = 3,
        *,
        azure_endpoint: str = "",
        api_version: str = "2024-10-21",
        azure_deployment: str | None = None,
        **kw,
    ):
        self._azure_endpoint = azure_endpoint
        self._api_version = api_version
        self._azure_deployment = azure_deployment
        # Skip base __init__ client creation; we override _make_client
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            max_retries=max_retries,
            **kw,
        )

    def _make_client(self) -> openai.AsyncOpenAI:
        """Create AsyncAzureOpenAI client."""
        return openai.AsyncAzureOpenAI(  # type: ignore[return-value]
            api_key=self._api_key,
            azure_endpoint=self._azure_endpoint,
            api_version=self._api_version,
            azure_deployment=self._azure_deployment,
        )

    async def health_check(self) -> bool:
        """Azure doesn't support model listing the same way."""
        return bool(self._api_key and self._azure_endpoint)
