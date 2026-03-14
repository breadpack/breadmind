import aiohttp
from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3",
    ):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
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

        return LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            ),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self._base_url}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False
