import anthropic
from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-6"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        kwargs = {
            "model": model or self._default_model,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = [self._convert_tool(t) for t in tools]

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    async def health_check(self) -> bool:
        try:
            await self._client.messages.create(
                model=self._default_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == "system":
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
        return result

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
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
        )
