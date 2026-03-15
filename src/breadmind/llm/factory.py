from __future__ import annotations

import os
from typing import Any

from .base import LLMProvider

_PROVIDER_REGISTRY: dict[str, tuple[type, str | None]] = {}  # name -> (class, env_key)


def register_provider(name: str, cls: type, env_key: str | None = None) -> None:
    """Provider를 레지스트리에 등록한다."""
    _PROVIDER_REGISTRY[name] = (cls, env_key)


def create_provider(config: Any) -> LLMProvider:
    """설정에 따라 적절한 LLMProvider 인스턴스를 생성한다.

    Registry에 등록된 provider를 찾아 생성하며,
    API 키가 설정되지 않은 경우 Ollama로 폴백한다.
    """
    name = config.llm.default_provider

    # CLI provider는 특수 케이스로 별도 처리
    if name == "cli":
        from breadmind.llm.cli import CLIProvider

        model = config.llm.default_model or "claude -p"
        parts = model.split()
        return CLIProvider(command=parts[0], args=parts[1:], name="cli")

    entry = _PROVIDER_REGISTRY.get(name)
    if entry is None:
        from breadmind.llm.ollama import OllamaProvider

        return OllamaProvider()

    cls, env_key = entry
    if env_key:
        api_key = os.environ.get(env_key, "")
        if not api_key:
            from breadmind.llm.ollama import OllamaProvider

            print(f"Warning: {env_key} not set, falling back to ollama")
            return OllamaProvider()
        return cls(api_key=api_key, default_model=config.llm.default_model)

    return cls()


# Provider 자동 등록
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.gemini import GeminiProvider
from breadmind.llm.grok import GrokProvider
from breadmind.llm.ollama import OllamaProvider

register_provider("claude", ClaudeProvider, "ANTHROPIC_API_KEY")
register_provider("gemini", GeminiProvider, "GEMINI_API_KEY")
register_provider("grok", GrokProvider, "XAI_API_KEY")
register_provider("ollama", OllamaProvider, None)
