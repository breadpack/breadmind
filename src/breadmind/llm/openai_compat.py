"""OpenAI-compatible provider base class.

Extracts shared logic from GrokProvider for reuse across providers
that implement the OpenAI chat completions API.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

import openai
from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Base class for providers using an OpenAI-compatible API."""

    # Subclasses MUST override these
    PROVIDER_NAME: str = "openai_compat"
    BASE_URL: str = ""
    DEFAULT_MODEL: str = ""

    # Subclasses MAY override these
    SUPPORTS_STREAMING: bool = True
    SUPPORTS_TOOL_CALLS: bool = True

    def __init__(
        self,
        api_key: str,
        default_model: str | None = None,
        max_retries: int = 3,
        *,
        api_keys: list[str] | None = None,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self._api_key = api_key
        self._default_model = default_model or self.DEFAULT_MODEL
        self.model = self._default_model
        self._max_retries = max_retries
        self._base_url = base_url or self.BASE_URL
        self._extra_headers = extra_headers or {}
        self._client = self._make_client()

    def _make_client(self) -> openai.AsyncOpenAI:
        """Create the async OpenAI client. Override for Azure etc."""
        kwargs: dict = {
            "api_key": self._api_key,
            "base_url": self._base_url,
        }
        headers = {**self._extra_headers, **self._extra_default_headers()}
        if headers:
            kwargs["default_headers"] = headers
        return openai.AsyncOpenAI(**kwargs)

    def _extra_default_headers(self) -> dict[str, str]:
        """Return additional default headers. Override in subclasses."""
        return {}

    def _extra_chat_kwargs(self, kwargs: dict) -> dict:
        """Add provider-specific kwargs before the API call. Override in subclasses."""
        return kwargs

    # -- public API --

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        kwargs: dict = {
            "model": model or self._default_model,
            "max_tokens": 4096,
            "messages": api_messages,
        }

        if tools and self.SUPPORTS_TOOL_CALLS:
            kwargs["tools"] = self._convert_tools(tools)

        kwargs = self._extra_chat_kwargs(kwargs)

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                return self._parse_response(response)
            except openai.RateLimitError as e:
                last_error = e
                backoff = 2 ** attempt
                logger.warning(
                    "%s rate limited (attempt %d/%d), retrying in %ds",
                    self.PROVIDER_NAME, attempt + 1, self._max_retries, backoff,
                )
                await asyncio.sleep(backoff)
            except openai.APIError as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

        raise last_error  # type: ignore[misc]

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        if not self.SUPPORTS_STREAMING:
            async for chunk in super().chat_stream(messages, tools, model):
                yield chunk
            return

        api_messages = self._convert_messages(messages)
        kwargs: dict = {
            "model": model or self._default_model,
            "max_tokens": 4096,
            "messages": api_messages,
            "stream": True,
        }

        if tools and self.SUPPORTS_TOOL_CALLS:
            kwargs["tools"] = self._convert_tools(tools)

        kwargs = self._extra_chat_kwargs(kwargs)

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            # Fallback: just verify we have an API key
            return bool(self._api_key)

    async def close(self) -> None:
        await self._client.close()

    @property
    def model_name(self) -> str:
        return self._default_model

    # -- conversion helpers --

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict]:
        # Consolidate mid-list system messages to the lead system slot. Some
        # OpenAI-compatible backends (xAI Grok, certain Azure deployments)
        # reject system messages that appear after non-system turns. P1
        # tool-recall wiring appends ``LLMMessage(role="system")`` after tool
        # results, so we proactively merge them here to keep the payload
        # shape uniform across all OpenAI-compat providers.
        messages = self._normalize_messages(messages)

        result: list[dict] = []
        for msg in messages:
            if msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                })
            elif msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                content = msg.content or ""
                # Check for attachments in metadata (vision support)
                attachments = getattr(msg, "attachments", None)
                if attachments:
                    parts: list[dict] = [{"type": "text", "text": content}]
                    for att in attachments:
                        if hasattr(att, "mime_type") and att.mime_type.startswith("image/"):
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": att.url},
                            })
                    result.append({"role": msg.role, "content": parts})
                else:
                    result.append({"role": msg.role, "content": content})
        return result

    @staticmethod
    def _normalize_messages(messages: list[LLMMessage]) -> list[LLMMessage]:
        """Collapse all ``role="system"`` messages into a single leading system.

        Preserves order of the system fragments (joined with ``\\n\\n``) so
        the original prompt remains first and any later P1 prior_runs
        recalls follow it. Non-system messages keep their relative order.
        """
        system_fragments: list[str] = []
        rest: list[LLMMessage] = []
        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_fragments.append(msg.content)
                continue
            rest.append(msg)

        if not system_fragments:
            return rest

        merged_system = LLMMessage(
            role="system",
            content="\n\n".join(system_fragments),
        )
        return [merged_system, *rest]

    @staticmethod
    def _convert_tools(tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def _parse_response(self, response) -> LLMResponse:
        choice = response.choices[0] if response.choices else None
        if not choice:
            return LLMResponse(
                content=f"No response from {self.PROVIDER_NAME}",
                tool_calls=[],
                usage=TokenUsage(input_tokens=0, output_tokens=0),
                stop_reason="error",
            )

        message = choice.message
        content = message.content
        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = response.usage
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )
