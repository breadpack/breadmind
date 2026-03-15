from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .base import LLMProvider


@dataclass
class ProviderInfo:
    name: str           # provider id (e.g. "gemini")
    cls: type           # provider class
    env_key: str | None # env var for API key (None = no key needed)
    display_name: str = ""
    models: list[str] | None = None
    free_tier: bool = False
    signup_url: str = ""


_PROVIDER_REGISTRY: dict[str, ProviderInfo] = {}


def register_provider(
    name: str, cls: type, env_key: str | None = None, *,
    display_name: str = "", models: list[str] | None = None,
    free_tier: bool = False, signup_url: str = "",
) -> None:
    _PROVIDER_REGISTRY[name] = ProviderInfo(
        name=name, cls=cls, env_key=env_key,
        display_name=display_name or name.capitalize(),
        models=models or [], free_tier=free_tier, signup_url=signup_url,
    )


def get_registered_providers() -> dict[str, ProviderInfo]:
    return dict(_PROVIDER_REGISTRY)


def get_provider_options() -> list[dict]:
    """Return provider list for setup wizard / UI."""
    return [
        {
            "id": info.name,
            "name": info.display_name,
            "env_key": info.env_key,
            "models": info.models,
            "free_tier": info.free_tier,
            "signup_url": info.signup_url,
        }
        for info in _PROVIDER_REGISTRY.values()
        if info.name != "cli"  # CLI is internal
    ]


def get_valid_provider_names() -> tuple[str, ...]:
    return tuple(_PROVIDER_REGISTRY.keys()) + ("cli",)


def get_env_key_to_provider_map() -> dict[str, str]:
    return {
        info.env_key: info.name
        for info in _PROVIDER_REGISTRY.values()
        if info.env_key
    }


def create_provider(config: Any) -> LLMProvider:
    name = config.llm.default_provider

    if name == "cli":
        from breadmind.llm.cli import CLIProvider
        model = config.llm.default_model or "claude -p"
        parts = model.split()
        return CLIProvider(command=parts[0], args=parts[1:], name="cli")

    info = _PROVIDER_REGISTRY.get(name)
    if info is None:
        from breadmind.llm.ollama import OllamaProvider
        return OllamaProvider()

    if info.env_key:
        api_key = os.environ.get(info.env_key, "")
        if not api_key:
            from breadmind.llm.ollama import OllamaProvider
            print(f"Warning: {info.env_key} not set, falling back to ollama")
            return OllamaProvider()
        return info.cls(api_key=api_key, default_model=config.llm.default_model)

    return info.cls()


# --- Provider 자동 등록 (Single Source of Truth) ---
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.gemini import GeminiProvider
from breadmind.llm.grok import GrokProvider
from breadmind.llm.ollama import OllamaProvider

register_provider("gemini", GeminiProvider, "GEMINI_API_KEY",
                   display_name="Google Gemini", free_tier=True,
                   models=["gemini-2.5-flash", "gemini-2.5-pro"],
                   signup_url="https://aistudio.google.com/apikey")
register_provider("claude", ClaudeProvider, "ANTHROPIC_API_KEY",
                   display_name="Anthropic Claude",
                   models=["claude-sonnet-4-6", "claude-haiku-4-5"],
                   signup_url="https://console.anthropic.com/settings/keys")
register_provider("grok", GrokProvider, "XAI_API_KEY",
                   display_name="xAI Grok",
                   models=["grok-3", "grok-3-mini"],
                   signup_url="https://console.x.ai/")
register_provider("ollama", OllamaProvider, None,
                   display_name="Ollama (Local)", free_tier=True,
                   models=["llama3.1", "mistral", "qwen2.5"],
                   signup_url="https://ollama.com/download")
