from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
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
        raw_key = os.environ.get(info.env_key, "")
        if not raw_key:
            from breadmind.llm.ollama import OllamaProvider
            print(f"Warning: {info.env_key} not set, falling back to ollama")
            return OllamaProvider()

        keys = [k.strip() for k in raw_key.split(",") if k.strip()]
        if len(keys) > 1:
            return info.cls(
                api_key=keys[0],
                default_model=config.llm.default_model,
                api_keys=keys,
            )
        return info.cls(api_key=keys[0], default_model=config.llm.default_model)

    return info.cls()


# --- Provider 자동 등록 (Single Source of Truth) ---
from breadmind.llm.claude import ClaudeProvider  # noqa: E402
from breadmind.llm.gemini import GeminiProvider  # noqa: E402
from breadmind.llm.grok import GrokProvider  # noqa: E402
from breadmind.llm.ollama import OllamaProvider  # noqa: E402

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


# --- Auth Profile Rotation ---

@dataclass
class AuthProfile:
    """An API key / auth credential for a provider."""
    key: str
    name: str = ""
    cooldown_until: float = 0  # timestamp when cooldown ends
    failure_count: int = 0


class AuthRotator:
    """Rotates through multiple auth profiles for a provider."""

    def __init__(self, profiles: list[AuthProfile]) -> None:
        self._profiles = profiles
        self._current_idx = 0

    def get_current(self) -> AuthProfile | None:
        """Get current active profile (skipping cooled-down ones)."""
        now = time.time()
        for _ in range(len(self._profiles)):
            profile = self._profiles[self._current_idx]
            if now >= profile.cooldown_until:
                return profile
            self._current_idx = (self._current_idx + 1) % len(self._profiles)
        return None  # all in cooldown

    def report_failure(self, cooldown_seconds: float = 60) -> AuthProfile | None:
        """Mark current profile as failed, advance to next."""
        profile = self._profiles[self._current_idx]
        profile.failure_count += 1
        profile.cooldown_until = time.time() + cooldown_seconds
        self._current_idx = (self._current_idx + 1) % len(self._profiles)
        return self.get_current()

    def report_success(self) -> None:
        """Reset failure count for current profile."""
        self._profiles[self._current_idx].failure_count = 0

    @property
    def active_count(self) -> int:
        now = time.time()
        return sum(1 for p in self._profiles if now >= p.cooldown_until)
