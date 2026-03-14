from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse, ToolCall
from breadmind.tools.registry import ToolRegistry
from breadmind.core.safety import SafetyGuard, SafetyResult

class CoreAgent:
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        system_prompt: str = "You are BreadMind, an AI infrastructure agent.",
        max_turns: int = 10,
    ):
        self._provider = provider
        self._tools = tool_registry
        self._guard = safety_guard
        self._system_prompt = system_prompt
        self._max_turns = max_turns

    async def handle_message(self, message: str, user: str, channel: str) -> str:
        messages = [
            LLMMessage(role="system", content=self._system_prompt),
            LLMMessage(role="user", content=message),
        ]
        tools = self._tools.get_all_definitions()

        for turn in range(self._max_turns):
            response = await self._provider.chat(messages=messages, tools=tools or None)

            if not response.has_tool_calls:
                return response.content or ""

            # Process tool calls
            for tc in response.tool_calls:
                safety = self._guard.check(tc.name, tc.arguments, user=user, channel=channel)

                if safety == SafetyResult.DENY:
                    messages.append(LLMMessage(
                        role="assistant", tool_calls=[tc],
                    ))
                    messages.append(LLMMessage(
                        role="tool", content=f"BLOCKED: {tc.name} is in the blacklist.",
                        tool_call_id=tc.id, name=tc.name,
                    ))
                    continue

                if safety == SafetyResult.REQUIRE_APPROVAL:
                    messages.append(LLMMessage(
                        role="assistant", tool_calls=[tc],
                    ))
                    messages.append(LLMMessage(
                        role="tool",
                        content=f"PENDING_APPROVAL: {tc.name} requires user approval. Inform the user.",
                        tool_call_id=tc.id, name=tc.name,
                    ))
                    continue

                # Execute tool
                result = await self._tools.execute(tc.name, tc.arguments)
                messages.append(LLMMessage(
                    role="assistant", tool_calls=[tc],
                ))
                messages.append(LLMMessage(
                    role="tool", content=result.output,
                    tool_call_id=tc.id, name=tc.name,
                ))

        return "Maximum tool call turns reached. Please try a simpler request."
