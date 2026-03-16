from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

import anthropic
from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)
from .rate_limiter import RateLimiter
from .token_counter import TokenCounter

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class ClaudeProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-6",
        rate_limiter: RateLimiter | None = None,
    ):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._rate_limiter = rate_limiter

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        system_prompt, api_messages = self._convert_messages(messages)
        use_thinking = think_budget is not None and think_budget > 0
        kwargs: dict = {
            "model": model or self._default_model,
            "max_tokens": 16384 if use_thinking else 4096,
            "messages": api_messages,
        }

        # Extended thinking: allows deeper reasoning for complex tasks
        if use_thinking:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": think_budget,
            }

        # 시스템 프롬프트가 있으면 system 파라미터로 전달 (캐시 제어 포함)
        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if tools:
            converted_tools = [self._convert_tool(t) for t in tools]
            # 마지막 도구에 캐시 제어 추가
            if converted_tools:
                converted_tools[-1]["cache_control"] = {"type": "ephemeral"}
            kwargs["tools"] = converted_tools

        # Rate limiter: estimate tokens and acquire before calling API
        estimated_tokens = 0
        if self._rate_limiter:
            estimated_tokens = TokenCounter.estimate_messages_tokens(messages)
            if tools:
                estimated_tokens += TokenCounter.estimate_tools_tokens(tools)
            await self._rate_limiter.acquire(estimated_tokens)

        # Retry with exponential backoff on 429 RateLimitError
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(**kwargs)
                result = self._parse_response(response)

                # Record actual usage
                if self._rate_limiter:
                    await self._rate_limiter.record_usage(result.usage.total_tokens)

                return result
            except anthropic.RateLimitError as e:
                last_error = e
                backoff = 2**attempt
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %ds",
                    attempt + 1,
                    _MAX_RETRIES,
                    backoff,
                )
                await asyncio.sleep(backoff)

        raise last_error  # type: ignore[misc]

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """스트리밍 방식으로 응답을 반환한다."""
        system_prompt, api_messages = self._convert_messages(messages)
        kwargs: dict = {
            "model": model or self._default_model,
            "max_tokens": 4096,
            "messages": api_messages,
        }

        if system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        if tools:
            converted_tools = [self._convert_tool(t) for t in tools]
            if converted_tools:
                converted_tools[-1]["cache_control"] = {"type": "ephemeral"}
            kwargs["tools"] = converted_tools

        # 스트리밍 컨텍스트 매니저를 사용하여 텍스트 델타를 순차적으로 반환
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def health_check(self) -> bool:
        """클라이언트 설정 상태만 확인한다. 불필요한 API 호출을 하지 않는다."""
        try:
            # API 키가 설정되어 있는지 확인
            return self._client.api_key is not None and len(self._client.api_key) > 0
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.close()

    @property
    def model_name(self) -> str:
        return self._default_model

    def _convert_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[dict]]:
        """메시지를 변환하고, 시스템 메시지를 별도로 추출한다."""
        system_parts: list[str] = []
        result: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                # 시스템 메시지를 별도로 수집
                if msg.content:
                    system_parts.append(msg.content)
                continue
            if msg.role == "tool":
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content or "",
                    }],
                })
            elif msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                        for tc in msg.tool_calls
                    ],
                })
            else:
                result.append({"role": msg.role, "content": msg.content or ""})

        # 여러 시스템 메시지가 있으면 합친다
        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return system_prompt, result

    def _convert_tool(self, tool: ToolDefinition) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }

    def _parse_response(self, response) -> LLMResponse:
        content = None
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        usage = response.usage
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=getattr(
                    usage, "cache_creation_input_tokens", 0
                ) or 0,
                cache_read_input_tokens=getattr(
                    usage, "cache_read_input_tokens", 0
                ) or 0,
            ),
            stop_reason=response.stop_reason,
        )
