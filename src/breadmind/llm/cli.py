import asyncio
import json
from .base import (
    LLMProvider,
    LLMResponse,
    LLMMessage,
    ToolCall,
    TokenUsage,
    ToolDefinition,
)


class CLIProvider(LLMProvider):
    """Subprocess-based provider for CLI tools (claude -p, gemini, codex).
    Personal/local use only. See Anthropic ToS for usage policy."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        name: str = "cli",
    ):
        self._command = command
        self._args = args or []
        self._name = name

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        prompt = self._build_prompt(messages, tools)
        proc = await asyncio.create_subprocess_exec(
            self._command, *self._args, prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()

        tool_calls = []
        content = output
        if tools:
            parsed = self._try_parse_tool_calls(output)
            if parsed:
                tool_calls = parsed
                content = None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    async def health_check(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._command, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def close(self) -> None:
        """서브프로세스 기반이므로 별도 정리가 필요 없다."""

    @property
    def model_name(self) -> str:
        return self._name

    def _build_prompt(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None,
    ) -> str:
        parts = []
        if tools:
            tool_descriptions = json.dumps(
                [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                    for t in tools
                ],
                indent=2,
            )
            parts.append(f"Available tools:\n{tool_descriptions}\n")
            parts.append(
                "If you need to use a tool, respond ONLY with JSON: "
                '{"tool_calls": [{"name": "...", "arguments": {...}}]}\n'
            )
        for msg in messages:
            if msg.role != "system":
                parts.append(f"{msg.role}: {msg.content}")
        return "\n".join(parts)

    def _try_parse_tool_calls(self, output: str) -> list[ToolCall] | None:
        try:
            data = json.loads(output)
            if "tool_calls" in data:
                return [
                    ToolCall(
                        id=f"cli_{i}",
                        name=tc["name"],
                        arguments=tc.get("arguments", {}),
                    )
                    for i, tc in enumerate(data["tool_calls"])
                ]
        except (json.JSONDecodeError, KeyError):
            pass
        return None
