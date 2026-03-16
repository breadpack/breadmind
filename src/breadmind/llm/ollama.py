from __future__ import annotations

import aiohttp
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

# 헬스체크 타임아웃 (초)
_HEALTH_CHECK_TIMEOUT = 5


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3",
        rate_limiter: RateLimiter | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._rate_limiter = rate_limiter

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        payload = {
            "model": model or self._default_model,
            "messages": [
                {"role": m.role, "content": m.content or ""} for m in messages
            ],
            "stream": False,
        }
        if tools:
            payload["tools"] = [
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

        # Rate limiter: estimate tokens and acquire before calling API
        if self._rate_limiter:
            estimated_tokens = TokenCounter.estimate_messages_tokens(messages)
            if tools:
                estimated_tokens += TokenCounter.estimate_tools_tokens(tools)
            await self._rate_limiter.acquire(estimated_tokens)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/api/chat", json=payload
            ) as resp:
                data = await resp.json()

        msg = data.get("message", {})
        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_calls.append(ToolCall(
                id=fn.get("name", ""),
                name=fn.get("name", ""),
                arguments=fn.get("arguments", {}),
            ))

        result = LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            ),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

        if self._rate_limiter:
            await self._rate_limiter.record_usage(result.usage.total_tokens)

        return result

    async def health_check(self) -> bool:
        """Ollama 서버 상태를 확인한다. 타임아웃을 설정하여 행(hang)을 방지한다."""
        try:
            timeout = aiohttp.ClientTimeout(total=_HEALTH_CHECK_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self._base_url}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def close(self) -> None:
        """매 호출마다 세션을 생성하므로 별도 정리가 필요 없다."""

    @property
    def model_name(self) -> str:
        return self._default_model
