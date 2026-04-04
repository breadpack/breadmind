from __future__ import annotations

import asyncio
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

_MAX_RETRIES = 3


class GrokProvider(LLMProvider):
    """xAI Grok provider (OpenAI-compatible API)."""

    def __init__(self, api_key: str, default_model: str = "grok-3"):
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        self._default_model = default_model
        self.model = default_model

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

        if tools:
            kwargs["tools"] = [
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

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.chat.completions.create(**kwargs)
                return self._parse_response(response)
            except openai.RateLimitError as e:
                last_error = e
                backoff = 2 ** attempt
                logger.warning(
                    "Grok rate limited (attempt %d/%d), retrying in %ds",
                    attempt + 1, _MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
            except openai.APIError as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
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
        """OpenAI 호환 스트리밍 API로 응답을 반환한다."""
        api_messages = self._convert_messages(messages)
        kwargs: dict = {
            "model": model or self._default_model,
            "max_tokens": 4096,
            "messages": api_messages,
            "stream": True,
        }
        # 스트리밍에서는 tools 없이 텍스트만 (tool call turn은 비스트리밍으로 처리)

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.APIError as e:
            logger.error("Grok streaming error: %s", e)
            # 스트리밍 실패 시 일반 chat()으로 폴백
            response = await self.chat(messages, tools, model)
            if response.content:
                yield response.content

    async def health_check(self) -> bool:
        try:
            return bool(self._client.api_key)
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.close()

    @property
    def model_name(self) -> str:
        return self._default_model

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict]:
        result: list[dict] = []
        for msg in messages:
            if msg.role == "tool":
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                })
            elif msg.tool_calls:
                import json
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
                result.append({
                    "role": msg.role,
                    "content": msg.content or "",
                })
        return result

    def _parse_response(self, response) -> LLMResponse:
        choice = response.choices[0] if response.choices else None
        if not choice:
            return LLMResponse(
                content="No response from Grok",
                tool_calls=[],
                usage=TokenUsage(input_tokens=0, output_tokens=0),
                stop_reason="error",
            )

        message = choice.message
        content = message.content
        tool_calls = []

        if message.tool_calls:
            import json
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
