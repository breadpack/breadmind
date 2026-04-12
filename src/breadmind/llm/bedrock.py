"""AWS Bedrock provider using the Converse API.

Requires `boto3` (optional dependency). Falls back gracefully if not installed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

try:
    import boto3
    _HAS_BOTO3 = True
except ImportError:
    _HAS_BOTO3 = False


class BedrockProvider(LLMProvider):
    """AWS Bedrock provider via the Converse API."""

    def __init__(
        self,
        default_model: str = "anthropic.claude-sonnet-4-6-20250514-v1:0",
        *,
        region_name: str = "us-east-1",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        # accept api_key for factory compatibility (ignored)
        api_key: str = "",
    ):
        if not _HAS_BOTO3:
            raise ImportError(
                "boto3 is required for BedrockProvider. "
                "Install it with: pip install boto3"
            )
        self._default_model = default_model
        self.model = default_model
        session_kwargs: dict[str, Any] = {"region_name": region_name}
        if aws_access_key_id:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
        if aws_session_token:
            session_kwargs["aws_session_token"] = aws_session_token
        session = boto3.Session(**session_kwargs)
        self._client = session.client("bedrock-runtime")

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        import asyncio

        converse_messages, system_prompts = self._convert_messages(messages)
        kwargs: dict[str, Any] = {
            "modelId": model or self._default_model,
            "messages": converse_messages,
        }
        if system_prompts:
            kwargs["system"] = system_prompts
        if tools:
            kwargs["toolConfig"] = {
                "tools": self._convert_tools(tools),
            }

        # boto3 is synchronous; run in executor
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._client.converse(**kwargs)
        )
        return self._parse_response(response)

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        # Fallback to non-streaming
        response = await self.chat(messages, tools, model)
        if response.content:
            yield response.content

    async def health_check(self) -> bool:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._client.list_foundation_models(byOutputModality="TEXT"),
            )
            return True
        except Exception:
            return False

    async def close(self) -> None:
        pass  # boto3 client doesn't need explicit close

    @property
    def model_name(self) -> str:
        return self._default_model

    # -- conversion helpers --

    @staticmethod
    def _convert_messages(
        messages: list[LLMMessage],
    ) -> tuple[list[dict], list[dict]]:
        """Convert to Bedrock Converse format.

        Returns (messages, system_prompts).
        """
        converse_msgs: list[dict] = []
        system_prompts: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                system_prompts.append({"text": msg.content or ""})
            elif msg.role == "tool":
                converse_msgs.append({
                    "role": "user",
                    "content": [{
                        "toolResult": {
                            "toolUseId": msg.tool_call_id or "",
                            "content": [{"text": msg.content or ""}],
                        }
                    }],
                })
            elif msg.tool_calls:
                content: list[dict] = []
                if msg.content:
                    content.append({"text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "toolUse": {
                            "toolUseId": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    })
                converse_msgs.append({"role": "assistant", "content": content})
            else:
                converse_msgs.append({
                    "role": msg.role,
                    "content": [{"text": msg.content or ""}],
                })

        return converse_msgs, system_prompts

    @staticmethod
    def _convert_tools(tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "toolSpec": {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": {"json": t.parameters},
                }
            }
            for t in tools
        ]

    @staticmethod
    def _parse_response(response: dict) -> LLMResponse:
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(ToolCall(
                    id=tu.get("toolUseId", ""),
                    name=tu.get("name", ""),
                    arguments=tu.get("input", {}),
                ))

        usage_info = response.get("usage", {})
        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=usage_info.get("inputTokens", 0),
                output_tokens=usage_info.get("outputTokens", 0),
            ),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )
