from __future__ import annotations
from typing import Any
from breadmind.core.protocols import (
    CacheStrategy, LLMResponse, Message, PromptBlock, ProviderProtocol, TokenUsage, ToolCallRequest,
)

SUPPORTED_FEATURES = frozenset({"thinking_blocks", "system_reminder", "prompt_caching", "tool_search"})


class ClaudeAdapter:
    """Claude API ProviderProtocol 구현."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6",
                 fallback_provider: ProviderProtocol | None = None, max_tokens: int = 16384) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback = fallback_provider
        self._max_tokens = max_tokens
        self._client: Any = None
        self._system_blocks: list[PromptBlock] = []

    def set_system_blocks(self, blocks: list[PromptBlock]) -> None:
        """system prompt 블록을 설정하여 prompt caching에 활용."""
        self._system_blocks = blocks

    @staticmethod
    def _sort_blocks_for_cache(blocks: list[PromptBlock]) -> list[PromptBlock]:
        """cacheable 블록을 앞에, priority 오름차순으로 정렬."""
        return sorted(blocks, key=lambda b: (not b.cacheable, b.priority))

    @staticmethod
    def _apply_tool_cache_control(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """마지막 tool에 cache_control을 추가."""
        if not tools:
            return tools
        result = [dict(t) for t in tools]
        result[-1]["cache_control"] = {"type": "ephemeral"}
        return result

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def chat(self, messages: list[Message], tools: list[Any] | None = None,
                   think_budget: int | None = None) -> LLMResponse:
        client = self._get_client()
        api_messages = self.transform_messages(messages)
        system_msgs = [m for m in api_messages if m["role"] == "system"]
        chat_msgs = [m for m in api_messages if m["role"] != "system"]
        kwargs: dict[str, Any] = {"model": self._model, "max_tokens": self._max_tokens, "messages": chat_msgs}
        if system_msgs:
            # system prompt를 content block 배열로 전달 (prompt caching 지원)
            if self._system_blocks:
                sorted_blocks = self._sort_blocks_for_cache(self._system_blocks)
                kwargs["system"] = self.transform_system_prompt(sorted_blocks)
            else:
                kwargs["system"] = "\n\n".join(m["content"] for m in system_msgs)
        if tools:
            kwargs["tools"] = self._apply_tool_cache_control(tools)
        if think_budget:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": think_budget}
        try:
            response = await client.messages.create(**kwargs)
        except Exception:
            if self._fallback:
                return await self._fallback.chat(messages, tools, think_budget)
            raise
        tool_calls = []
        content = None
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(id=block.id, name=block.name, arguments=block.input))
        usage = response.usage
        return LLMResponse(content=content, tool_calls=tool_calls,
                          usage=TokenUsage(
                              input_tokens=usage.input_tokens,
                              output_tokens=usage.output_tokens,
                              cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                              cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                          ),
                          stop_reason=response.stop_reason)

    def get_cache_strategy(self) -> CacheStrategy:
        return CacheStrategy(name="claude_ephemeral", config={"type": "ephemeral"})

    def supports_feature(self, feature: str) -> bool:
        return feature in SUPPORTED_FEATURES

    def transform_system_prompt(self, blocks: list[PromptBlock]) -> list[dict[str, Any]]:
        result = []
        for block in blocks:
            param: dict[str, Any] = {"type": "text", "text": block.content}
            if block.cacheable:
                hints = block.provider_hints.get("claude", {})
                scope = hints.get("scope", "org")
                param["cache_control"] = {"type": "ephemeral", "scope": scope}
            result.append(param)
        return result

    def transform_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        result = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role}
            # 이미지 첨부가 있는 메시지: content block 배열로 변환
            if msg.attachments:
                content_blocks: list[dict[str, Any]] = []
                for att in msg.attachments:
                    if att.type == "image" and att.data and att.media_type:
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": att.media_type,
                                "data": att.data,
                            },
                        })
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                entry["content"] = content_blocks
            else:
                entry["content"] = msg.content or ""
            if msg.tool_calls:
                entry["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls]
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            result.append(entry)
        return result

    @property
    def fallback(self) -> ProviderProtocol | None:
        return self._fallback
