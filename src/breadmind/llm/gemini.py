from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import json
import aiohttp
from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)
from .retry import RetryConfig, retry_with_backoff, retry_with_backoff_stream
from breadmind.utils.helpers import generate_short_id

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from breadmind.core.http_pool import HTTPSessionManager

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class _GeminiHTTPError(Exception):
    """HTTP error with status code for retry logic detection."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "gemini-2.5-flash",
        retry_config: RetryConfig | None = None,
        session_manager: "HTTPSessionManager | None" = None,
    ):
        self._api_key = api_key
        self._default_model = default_model
        self.model = default_model
        self._retry_config = retry_config or RetryConfig()
        self._session_manager = session_manager

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        model_name = model or self._default_model
        url = f"{_API_BASE}/models/{model_name}:generateContent?key={self._api_key}"

        system_prompt, contents = self._convert_messages(messages)

        body: dict = {"contents": contents}

        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        if tools:
            body["tools"] = [{"functionDeclarations": [
                self._convert_tool(t) for t in tools
            ]}]

        body["generationConfig"] = {"maxOutputTokens": 8192}

        # Adjust thinking budget based on task complexity
        effective_budget = think_budget if think_budget is not None else 0
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": effective_budget}

        body["generationConfig"]["responseModalities"] = ["TEXT"]

        logger.debug("Gemini request body: %s", json.dumps(body, default=str)[:3000])

        async def _do_call() -> LLMResponse:
            if self._session_manager is not None:
                session = await self._session_manager.get_session("gemini")
            else:
                session = aiohttp.ClientSession()
            try:
                async with session.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 429:
                        raise _GeminiHTTPError(resp.status, "Rate limited")

                    if resp.status in {500, 502, 503, 529}:
                        error_text = await resp.text()
                        raise _GeminiHTTPError(
                            resp.status,
                            f"Gemini API error: HTTP {resp.status} - {error_text[:500]}",
                        )

                    if resp.status != 200:
                        error_text = await resp.text()
                        raise Exception(
                            f"Gemini API error: HTTP {resp.status} - {error_text[:500]}"
                        )

                    data = await resp.json()
                    logger.debug("Gemini raw response: %s", json.dumps(data, default=str)[:2000])
                    return self._parse_response(data)
            finally:
                if self._session_manager is None:
                    await session.close()

        return await retry_with_backoff(_do_call, config=self._retry_config)

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """스트리밍 방식으로 응답을 반환한다. Gemini streamGenerateContent API 사용."""
        model_name = model or self._default_model
        url = (
            f"{_API_BASE}/models/{model_name}:streamGenerateContent"
            f"?alt=sse&key={self._api_key}"
        )

        system_prompt, contents = self._convert_messages(messages)

        body: dict = {"contents": contents}

        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        # 스트리밍에서 tool_use가 오면 폴백 불가이므로 tools 없이 요청
        # (tool call turn은 handle_message_stream에서 비스트리밍 chat()으로 처리)

        body["generationConfig"] = {
            "maxOutputTokens": 8192,
            "responseModalities": ["TEXT"],
        }

        async def _do_stream() -> AsyncGenerator[str, None]:
            if self._session_manager is not None:
                session = await self._session_manager.get_session("gemini")
                owns_session = False
            else:
                session = aiohttp.ClientSession()
                owns_session = True
            try:
                async with session.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        if resp.status in {429, 500, 502, 503, 529}:
                            error_text = await resp.text()
                            raise _GeminiHTTPError(
                                resp.status,
                                f"Gemini streaming API error: HTTP {resp.status} - {error_text[:500]}",
                            )
                        error_text = await resp.text()
                        raise Exception(
                            f"Gemini streaming API error: HTTP {resp.status} - {error_text[:500]}"
                        )

                    # SSE 스트림 파싱: 각 라인은 "data: {json}" 형식
                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line or not line.startswith("data: "):
                                continue
                            json_str = line[6:]  # "data: " 이후
                            if json_str == "[DONE]":
                                return
                            try:
                                data = json.loads(json_str)
                            except json.JSONDecodeError:
                                continue
                            # 각 candidate의 text parts를 yield
                            for candidate in data.get("candidates", []):
                                for part in candidate.get("content", {}).get("parts", []):
                                    text = part.get("text")
                                    if text:
                                        yield text
            finally:
                if owns_session:
                    await session.close()

        try:
            async for chunk in retry_with_backoff_stream(
                _do_stream, config=self._retry_config
            ):
                yield chunk
        except Exception:
            logger.error("Gemini streaming failed after retries, falling back to chat()")
            response = await self.chat(messages, tools, model)
            if response.content:
                yield response.content

    async def health_check(self) -> bool:
        try:
            return bool(self._api_key)
        except Exception:
            return False

    async def close(self) -> None:
        """매 호출마다 세션을 생성하므로 별도 정리가 필요 없다."""

    @property
    def model_name(self) -> str:
        return self._default_model

    def _convert_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[dict]]:
        system_parts: list[str] = []
        contents: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
                continue

            if msg.role == "tool":
                contents.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.name or "tool",
                            "response": {"result": msg.content or ""},
                        }
                    }],
                })
            elif msg.tool_calls:
                parts = []
                for tc in msg.tool_calls:
                    # Use raw part from Gemini response if available (preserves thought_signature exactly)
                    raw_part = tc.metadata.get("_raw_part") if tc.metadata else None
                    if raw_part:
                        parts.append(raw_part)
                    else:
                        fc_part: dict = {
                            "functionCall": {
                                "name": tc.name,
                                "args": tc.arguments,
                            }
                        }
                        ts = tc.metadata.get("thought_signature") if tc.metadata else None
                        if ts:
                            fc_part["thought_signature"] = ts
                        parts.append(fc_part)
                contents.append({"role": "model", "parts": parts})
            elif msg.attachments:
                # 이미지 첨부가 있는 메시지: inline_data parts로 변환
                role = "model" if msg.role == "assistant" else "user"
                parts: list[dict] = []
                for att in msg.attachments:
                    if att.type == "image" and att.data and att.media_type:
                        parts.append({
                            "inline_data": {
                                "mime_type": att.media_type,
                                "data": att.data,
                            },
                        })
                if msg.content:
                    parts.append({"text": msg.content})
                contents.append({"role": role, "parts": parts})
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.content or ""}],
                })

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        contents = self._sanitize_turn_order(contents)
        return system_prompt, contents

    @staticmethod
    def _sanitize_turn_order(contents: list[dict]) -> list[dict]:
        """Fix message ordering to satisfy Gemini API constraints.

        Rules enforced:
        1. Conversation must start with a "user" turn.
        2. "user" and "model" turns must alternate (no consecutive same-role).
        3. "function" (tool response) turns must come immediately after a
           "model" turn that contains a functionCall.
        4. Orphaned function responses (no preceding functionCall) are dropped.
        5. Consecutive same-role turns are merged.
        """
        if not contents:
            return contents

        # Pass 1: merge consecutive same-role turns
        merged: list[dict] = []
        for entry in contents:
            role = entry.get("role", "")
            if merged and merged[-1].get("role") == role:
                # Merge parts into previous entry of same role
                merged[-1]["parts"].extend(entry.get("parts", []))
            else:
                merged.append(entry)

        # Pass 2: ensure function responses follow a model functionCall
        sanitized: list[dict] = []
        for entry in merged:
            role = entry.get("role", "")
            if role == "function":
                # Only keep if previous turn is a model with functionCall
                if sanitized and sanitized[-1].get("role") == "model":
                    has_fc = any(
                        "functionCall" in p
                        for p in sanitized[-1].get("parts", [])
                    )
                    if has_fc:
                        sanitized.append(entry)
                        continue
                # Orphaned function response — drop it
                logger.warning("Dropping orphaned function response turn")
                continue
            sanitized.append(entry)

        # Pass 3: ensure it starts with user turn
        if sanitized and sanitized[0].get("role") != "user":
            sanitized.insert(0, {
                "role": "user",
                "parts": [{"text": "(conversation continued)"}],
            })

        # Pass 4: fix any remaining consecutive same-role turns
        # (can happen after dropping orphaned function responses)
        fixed: list[dict] = []
        for entry in sanitized:
            role = entry.get("role", "")
            if fixed and fixed[-1].get("role") == role:
                fixed[-1]["parts"].extend(entry.get("parts", []))
            else:
                fixed.append(entry)

        return fixed

    def _convert_tool(self, tool: ToolDefinition) -> dict:
        params = dict(tool.parameters)
        # Gemini doesn't support additionalProperties in parameters
        params.pop("additionalProperties", None)
        # Clean properties too
        props = params.get("properties", {})
        cleaned_props = {}
        for k, v in props.items():
            cleaned = dict(v)
            cleaned.pop("additionalProperties", None)
            cleaned_props[k] = cleaned
        params["properties"] = cleaned_props

        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": params,
        }

    def _parse_response(self, data: dict) -> LLMResponse:
        candidates = data.get("candidates", [])
        if not candidates:
            return LLMResponse(
                content="No response from Gemini",
                tool_calls=[],
                usage=TokenUsage(input_tokens=0, output_tokens=0),
                stop_reason="error",
            )

        candidate = candidates[0]
        content_parts = candidate.get("content", {}).get("parts", [])

        text_content = None
        tool_calls = []

        for part in content_parts:
            if "text" in part:
                text_content = part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                metadata = {}
                # thought_signature can be at part level or inside functionCall
                ts = part.get("thought_signature") or fc.get("thought_signature")
                if ts:
                    metadata["thought_signature"] = ts
                # Save the raw part for exact round-trip
                metadata["_raw_part"] = part
                tool_calls.append(ToolCall(
                    id=generate_short_id(),
                    name=fc.get("name", ""),
                    arguments=fc.get("args", {}),
                    metadata=metadata,
                ))

        # Parse usage metadata
        usage_meta = data.get("usageMetadata", {})
        input_tokens = usage_meta.get("promptTokenCount", 0)
        output_tokens = usage_meta.get("candidatesTokenCount", 0)

        candidate.get("finishReason", "STOP")
        stop_reason = "tool_use" if tool_calls else "end_turn"

        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            stop_reason=stop_reason,
        )
