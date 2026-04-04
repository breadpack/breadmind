"""v2 CLI 런타임: stdin/stdout 기반 대화 루프."""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from breadmind.core.protocols import UserInput, AgentOutput, Progress


class CLIRuntime:
    """CLI 런타임. RuntimeProtocol 구현."""

    def __init__(self, agent: Any, prompt: str = "> ",
                 stream: bool = False) -> None:
        self._agent = agent
        self._prompt = prompt
        self._running = False
        self._stream = stream

    async def start(self, container: Any) -> None:
        self._running = True
        mode = "streaming" if self._stream else "standard"
        print(f"🤖 {self._agent.name} CLI [{mode}] (type 'exit' to quit)")
        print("-" * 40)

        while self._running:
            try:
                user_input = await self.receive()
                if user_input.text.lower() in ("exit", "quit", "/exit", "/quit"):
                    print("Goodbye!")
                    break

                if self._stream:
                    await self._run_stream(user_input.text)
                else:
                    response = await self._agent.run(user_input.text)
                    await self.send(AgentOutput(text=response))
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")

    async def _run_stream(self, message: str) -> None:
        """스트리밍 모드로 메시지 처리."""
        from breadmind.core.protocols import AgentContext, PromptBlock
        from breadmind.plugins.builtin.agent_loop.message_loop import (
            MessageLoopAgent,
        )

        agent = self._agent
        agent._build()

        provider = agent.plugins.get("provider")
        prompt_builder = agent.plugins.get("prompt_builder")
        tool_registry = agent.plugins.get("tool_registry")

        if provider is None:
            print("Error: Provider not configured")
            return

        if prompt_builder is None:
            class MinimalPromptBuilder:
                def build(self, ctx):
                    return [PromptBlock(
                        section="identity",
                        content=f"You are {ctx.persona_name}.",
                        cacheable=True, priority=1,
                    )]
            prompt_builder = MinimalPromptBuilder()

        if tool_registry is None:
            from breadmind.plugins.builtin.tools.registry import HybridToolRegistry
            tool_registry = HybridToolRegistry()

        loop_agent = MessageLoopAgent(
            provider=provider,
            prompt_builder=prompt_builder,
            tool_registry=tool_registry,
            safety_guard=agent._safety,
            max_turns=agent.config.max_turns,
            prompt_context=agent._prompt_context,
        )

        ctx = AgentContext(
            user="cli_user", channel="cli",
            session_id="cli_user:cli",
        )

        print()
        async for event in loop_agent.handle_message_stream(message, ctx):
            if event.type == "text":
                print(event.data, end="", flush=True)
            elif event.type == "tool_start":
                tools = event.data.get("tools", [])
                print(f"\n  [Tool: {', '.join(tools)}]", flush=True)
            elif event.type == "tool_end":
                results = event.data.get("results", [])
                status = ", ".join(
                    f"{r['name']}:{'ok' if r['success'] else 'fail'}"
                    for r in results
                )
                print(f"  [Done: {status}]", flush=True)
            elif event.type == "compact":
                print("  [Compacted]", flush=True)
            elif event.type == "error":
                print(f"\n  [Error: {event.data}]", flush=True)
            elif event.type == "done":
                tokens = event.data.get("tokens", 0)
                tc = event.data.get("tool_calls", 0)
                print(f"\n  [{tokens} tokens, {tc} tool calls]\n", flush=True)
        sys.stdout.flush()

    async def stop(self) -> None:
        self._running = False

    async def receive(self) -> UserInput:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, lambda: input(self._prompt))
        return UserInput(text=text.strip(), user="cli_user", channel="cli")

    async def send(self, output: AgentOutput) -> None:
        print(f"\n{output.text}\n")

    async def send_progress(self, progress: Progress) -> None:
        if progress.status == "thinking":
            print("  ⏳ Thinking...", end="\r")
        elif progress.status == "tool_executing":
            print(f"  🔧 {progress.detail}", end="\r")
