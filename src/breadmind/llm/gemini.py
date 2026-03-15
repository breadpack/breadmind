from __future__ import annotations

import asyncio
import logging
import uuid

import aiohttp
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
_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, api_key: str, default_model: str = "gemini-2.5-flash"):
        self._api_key = api_key
        self._default_model = default_model
        self.model = default_model

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
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

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=body,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status == 429:
                            backoff = 2 ** attempt
                            logger.warning(
                                "Gemini rate limited (attempt %d/%d), retrying in %ds",
                                attempt + 1, _MAX_RETRIES, backoff,
                            )
                            await asyncio.sleep(backoff)
                            last_error = Exception(f"Rate limited: HTTP {resp.status}")
                            continue

                        if resp.status != 200:
                            error_text = await resp.text()
                            raise Exception(
                                f"Gemini API error: HTTP {resp.status} - {error_text[:500]}"
                            )

                        data = await resp.json()
                        return self._parse_response(data)

            except aiohttp.ClientError as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

        raise last_error  # type: ignore[misc]

    async def health_check(self) -> bool:
        try:
            return bool(self._api_key)
        except Exception:
            return False

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
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                    })
                contents.append({"role": "model", "parts": parts})
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.content or ""}],
                })

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return system_prompt, contents

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
                tool_calls.append(ToolCall(
                    id=str(uuid.uuid4())[:8],
                    name=fc.get("name", ""),
                    arguments=fc.get("args", {}),
                ))

        # Parse usage metadata
        usage_meta = data.get("usageMetadata", {})
        input_tokens = usage_meta.get("promptTokenCount", 0)
        output_tokens = usage_meta.get("candidatesTokenCount", 0)

        finish_reason = candidate.get("finishReason", "STOP")
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
