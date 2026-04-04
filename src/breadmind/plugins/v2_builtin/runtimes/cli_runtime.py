"""v2 CLI 런타임: stdin/stdout 기반 대화 루프."""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from breadmind.core.protocols import UserInput, AgentOutput, Progress


class CLIRuntime:
    """CLI 런타임. RuntimeProtocol 구현."""

    def __init__(self, agent: Any, prompt: str = "> ") -> None:
        self._agent = agent
        self._prompt = prompt
        self._running = False

    async def start(self, container: Any) -> None:
        self._running = True
        print(f"🤖 {self._agent.name} CLI (type 'exit' to quit)")
        print("-" * 40)

        while self._running:
            try:
                user_input = await self.receive()
                if user_input.text.lower() in ("exit", "quit", "/exit", "/quit"):
                    print("Goodbye!")
                    break

                response = await self._agent.run(user_input.text)
                await self.send(AgentOutput(text=response))
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")

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
