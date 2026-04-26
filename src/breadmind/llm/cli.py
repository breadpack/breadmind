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
        # Lead system messages become a single "system:" preamble. Mid-list
        # system messages (e.g. P1 prior_runs recalls injected after a tool
        # result) are converted to user turns prefixed with "[system-recall]"
        # so the CLI subprocess still sees the content rather than dropping
        # it entirely. Position in the conversation is preserved.
        for msg in self._normalize_for_cli(messages):
            parts.append(f"{msg.role}: {msg.content}")
        return "\n".join(parts)

    @staticmethod
    def _normalize_messages(messages: list[LLMMessage]) -> list[LLMMessage]:
        """Merge leading system messages, convert mid-list to ``[system-recall]``.

        - Consecutive ``role="system"`` messages at the start are merged into
          one leading system message.
        - Any ``role="system"`` message that appears after a non-system turn
          is rewritten as a ``role="user"`` message whose content is prefixed
          with ``[system-recall]`` so the CLI subprocess still receives it.
        """
        result: list[LLMMessage] = []
        leading_system: list[str] = []
        seen_non_system = False

        for msg in messages:
            if msg.role == "system":
                if not seen_non_system:
                    if msg.content:
                        leading_system.append(msg.content)
                    continue
                # Mid-list system → demote to user with explicit prefix.
                if msg.content:
                    result.append(LLMMessage(
                        role="user",
                        content=f"[system-recall] {msg.content}",
                    ))
                continue
            if not seen_non_system and leading_system:
                result.append(LLMMessage(
                    role="system",
                    content="\n\n".join(leading_system),
                ))
                leading_system = []
            seen_non_system = True
            result.append(msg)

        # Edge case: messages were system-only (no non-system turns).
        if leading_system and not seen_non_system:
            result.append(LLMMessage(
                role="system",
                content="\n\n".join(leading_system),
            ))
        return result

    @classmethod
    def _normalize_for_cli(
        cls, messages: list[LLMMessage],
    ) -> list[LLMMessage]:
        """Backwards-compatible wrapper that drops the lead system message.

        The original CLI implementation skipped ``role="system"`` entirely
        on the assumption that the system prompt was passed via CLI flags.
        We preserve that behaviour for the *leading* system message and
        only surface mid-list system content (rewritten to user turns).
        """
        normalized = cls._normalize_messages(messages)
        if normalized and normalized[0].role == "system":
            return normalized[1:]
        return normalized

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
