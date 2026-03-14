import asyncio
import sys
from breadmind.config import load_config, load_safety_config
from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.ollama import OllamaProvider
from breadmind.tools.registry import ToolRegistry

def create_provider(config):
    provider_name = config.llm.default_provider
    if provider_name == "claude":
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        return ClaudeProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        return OllamaProvider()

async def run():
    config = load_config()
    safety_cfg = load_safety_config()

    provider = create_provider(config)
    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        max_turns=config.llm.tool_call_max_turns,
    )

    print("BreadMind v0.1.0 - AI Infrastructure Agent")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            break

        response = await agent.handle_message(user_input, user="local", channel="cli")
        print(f"breadmind> {response}\n")

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
