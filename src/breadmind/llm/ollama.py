from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

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
from .retry import RetryConfig, retry_with_backoff, retry_with_backoff_stream
from .token_counter import TokenCounter
from breadmind.constants import DEFAULT_OLLAMA_MODEL

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from breadmind.core.http_pool import HTTPSessionManager

logger = logging.getLogger(__name__)

# 헬스체크 타임아웃 (초)
_HEALTH_CHECK_TIMEOUT = 5


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = DEFAULT_OLLAMA_MODEL,
        rate_limiter: RateLimiter | None = None,
        retry_config: RetryConfig | None = None,
        session_manager: "HTTPSessionManager | None" = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._rate_limiter = rate_limiter
        self._retry_config = retry_config or RetryConfig()
        self._session_manager = session_manager

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

        async def _do_call() -> LLMResponse:
            if self._session_manager is not None:
                session = await self._session_manager.get_session("ollama")
            else:
                session = aiohttp.ClientSession()
            try:
                async with session.post(
                    f"{self._base_url}/api/chat", json=payload
                ) as resp:
                    data = await resp.json()
            finally:
                if self._session_manager is None:
                    await session.close()

            msg = data.get("message", {})
            tool_calls_list = []
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                tool_calls_list.append(ToolCall(
                    id=fn.get("name", ""),
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", {}),
                ))

            return LLMResponse(
                content=msg.get("content"),
                tool_calls=tool_calls_list,
                usage=TokenUsage(
                    input_tokens=data.get("prompt_eval_count", 0),
                    output_tokens=data.get("eval_count", 0),
                ),
                stop_reason="tool_use" if tool_calls_list else "end_turn",
            )

        result = await retry_with_backoff(_do_call, config=self._retry_config)

        if self._rate_limiter:
            await self._rate_limiter.record_usage(result.usage.total_tokens)

        return result

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Ollama 스트리밍 API로 응답을 반환한다. JSON line 파싱."""
        payload = {
            "model": model or self._default_model,
            "messages": [
                {"role": m.role, "content": m.content or ""} for m in messages
            ],
            "stream": True,
        }
        # 스트리밍에서는 tools 없이 텍스트만 (tool call turn은 비스트리밍으로 처리)

        async def _do_stream() -> AsyncGenerator[str, None]:
            if self._session_manager is not None:
                session = await self._session_manager.get_session("ollama")
                owns_session = False
            else:
                session = aiohttp.ClientSession()
                owns_session = True
            try:
                async with session.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise Exception(
                            f"Ollama streaming error: HTTP {resp.status} - {error_text[:500]}"
                        )

                    # Ollama 스트리밍: 각 라인이 독립 JSON 객체
                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            # message.content 필드에서 텍스트 추출
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            # done=true이면 스트림 종료
                            if data.get("done", False):
                                return
            finally:
                if owns_session:
                    await session.close()

        try:
            async for chunk in retry_with_backoff_stream(
                _do_stream, config=self._retry_config
            ):
                yield chunk
        except Exception:
            logger.error("Ollama streaming failed after retries, falling back to chat()")
            response = await self.chat(messages, tools, model)
            if response.content:
                yield response.content

    async def health_check(self) -> bool:
        """Ollama 서버 상태를 확인한다. 타임아웃을 설정하여 행(hang)을 방지한다."""
        try:
            timeout = aiohttp.ClientTimeout(total=_HEALTH_CHECK_TIMEOUT)
            if self._session_manager is not None:
                session = await self._session_manager.get_session("ollama")
                async with session.get(
                    f"{self._base_url}/api/tags", timeout=timeout,
                ) as resp:
                    return resp.status == 200
            else:
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
