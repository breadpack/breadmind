from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .base import LLMProvider


# A builder receives the per-provider settings dict (from config.llm.providers[name])
# and the full AppConfig, returning a ready-to-use LLMProvider.
ProviderBuilder = Callable[[dict[str, Any], Any], LLMProvider]


@dataclass
class ProviderInfo:
    name: str                   # provider id (e.g. "gemini")
    cls: type | None            # provider class (may be None when builder doesn't need it)
    env_key: str | None = None  # env var for API key (None = no key needed)
    display_name: str = ""
    models: list[str] = field(default_factory=list)
    free_tier: bool = False
    signup_url: str = ""
    builder: ProviderBuilder | None = None  # custom construction logic (optional)


_PROVIDER_REGISTRY: dict[str, ProviderInfo] = {}


def register_provider(
    name: str, cls: type | None, env_key: str | None = None, *,
    display_name: str = "", models: list[str] | None = None,
    free_tier: bool = False, signup_url: str = "",
    builder: ProviderBuilder | None = None,
) -> None:
    _PROVIDER_REGISTRY[name] = ProviderInfo(
        name=name, cls=cls, env_key=env_key,
        display_name=display_name or name.capitalize(),
        models=models or [], free_tier=free_tier, signup_url=signup_url,
        builder=builder,
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
    names = tuple(_PROVIDER_REGISTRY.keys())
    if "cli" not in names:
        names = names + ("cli",)
    return names


def get_env_key_to_provider_map() -> dict[str, str]:
    return {
        info.env_key: info.name
        for info in _PROVIDER_REGISTRY.values()
        if info.env_key
    }


# --- Builders --------------------------------------------------------------

def _default_builder(info: ProviderInfo) -> ProviderBuilder:
    """Default builder for API-key providers. Reads the env key, merges
    provider settings, and instantiates info.cls with the common kwargs.

    Provider-specific settings (config.llm.providers[name]) are forwarded
    as kwargs, so any provider-specific constructor param (e.g. azure
    endpoint, openrouter site_url) is supported without factory changes.
    """
    def build(settings: dict[str, Any], config: Any) -> LLMProvider:
        if info.cls is None:
            raise RuntimeError(f"Provider '{info.name}' has no cls and no custom builder")
        kwargs: dict[str, Any] = {"default_model": config.llm.default_model}
        if info.env_key:
            raw_key = os.environ.get(info.env_key, "")
            keys = [k.strip() for k in raw_key.split(",") if k.strip()]
            if keys:
                kwargs["api_key"] = keys[0]
                if len(keys) > 1:
                    kwargs["api_keys"] = keys
        # Provider-specific overrides (base_url, deployment, site_url, ...).
        kwargs.update(settings)
        return info.cls(**kwargs)
    return build


def _ollama_builder(settings: dict[str, Any], config: Any) -> LLMProvider:
    """Ollama needs base_url (optional) and a model name. When Ollama is the
    requested provider we honor config.llm.default_model; when reached via
    fallback we keep the Ollama-specific default so a Claude-named model
    doesn't leak into Ollama."""
    from breadmind.llm.ollama import OllamaProvider
    from breadmind.constants import DEFAULT_OLLAMA_MODEL, DEFAULT_OLLAMA_URL

    base_url = settings.get("base_url", DEFAULT_OLLAMA_URL)
    if config.llm.default_provider == "ollama" and config.llm.default_model:
        model = settings.get("default_model", config.llm.default_model)
    else:
        model = settings.get("default_model", DEFAULT_OLLAMA_MODEL)
    return OllamaProvider(base_url=base_url, default_model=model)


def _cli_builder(settings: dict[str, Any], config: Any) -> LLMProvider:
    """CLI provider: `command` in settings or fall back to default_model."""
    from breadmind.llm.cli import CLIProvider
    command_line = settings.get("command") or config.llm.default_model or "claude -p"
    parts = command_line.split()
    return CLIProvider(command=parts[0], args=parts[1:], name="cli")


# --- Public entry point ----------------------------------------------------

def create_provider(config: Any) -> LLMProvider:
    """Build the LLM provider for config.llm.default_provider. Falls back
    to config.llm.fallback_provider on unknown names or missing API keys."""
    return _create_by_name(config.llm.default_provider, config, visited=set())


def _create_by_name(name: str, config: Any, visited: set[str]) -> LLMProvider:
    if name in visited:
        raise RuntimeError(
            f"Fallback cycle detected while resolving provider: {sorted(visited | {name})}"
        )
    visited = visited | {name}

    info = _PROVIDER_REGISTRY.get(name)
    if info is None:
        fallback = config.llm.fallback_provider
        if fallback and fallback != name:
            print(f"Warning: provider '{name}' not registered, falling back to '{fallback}'")
            return _create_by_name(fallback, config, visited)
        raise ValueError(f"Unknown provider '{name}' and no fallback configured")

    if info.env_key and not os.environ.get(info.env_key, "").strip():
        fallback = config.llm.fallback_provider
        if fallback and fallback != name:
            print(f"Warning: {info.env_key} not set, falling back to '{fallback}'")
            return _create_by_name(fallback, config, visited)
        # If no fallback, let the provider itself decide how to fail.

    settings = config.llm.providers.get(name, {})
    builder = info.builder or _default_builder(info)
    return builder(settings, config)


# --- Provider auto-registration (Single Source of Truth) ------------------

# Core providers (always available)
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
                   signup_url="https://ollama.com/download",
                   builder=_ollama_builder)
register_provider("cli", None, None,
                   display_name="CLI Passthrough",
                   builder=_cli_builder)


# --- Auth Profile Rotation ------------------------------------------------

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


# --- OpenAI-compatible providers (always available — uses openai SDK) ----

from breadmind.llm.openai_provider import OpenAIProvider  # noqa: E402
from breadmind.llm.deepseek import DeepSeekProvider  # noqa: E402
from breadmind.llm.openrouter import OpenRouterProvider  # noqa: E402
from breadmind.llm.mistral import MistralProvider  # noqa: E402
from breadmind.llm.together import TogetherProvider  # noqa: E402
from breadmind.llm.groq_provider import GroqProvider  # noqa: E402
from breadmind.llm.azure_openai import AzureOpenAIProvider  # noqa: E402

register_provider("openai", OpenAIProvider, "OPENAI_API_KEY",
                   display_name="OpenAI",
                   models=["gpt-4o", "gpt-4o-mini", "o1", "o1-mini", "o3-mini"],
                   signup_url="https://platform.openai.com/api-keys")
register_provider("deepseek", DeepSeekProvider, "DEEPSEEK_API_KEY",
                   display_name="DeepSeek",
                   models=["deepseek-chat", "deepseek-reasoner"],
                   signup_url="https://platform.deepseek.com/api_keys")
register_provider("openrouter", OpenRouterProvider, "OPENROUTER_API_KEY",
                   display_name="OpenRouter (300+ models)",
                   models=["openai/gpt-4o", "anthropic/claude-sonnet-4-6",
                           "google/gemini-2.5-flash", "meta-llama/llama-3.1-405b"],
                   signup_url="https://openrouter.ai/keys")
register_provider("mistral", MistralProvider, "MISTRAL_API_KEY",
                   display_name="Mistral AI",
                   models=["mistral-large-latest", "mistral-medium-latest",
                           "mistral-small-latest", "codestral-latest"],
                   signup_url="https://console.mistral.ai/api-keys")
register_provider("together", TogetherProvider, "TOGETHER_API_KEY",
                   display_name="Together AI",
                   models=["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                           "mistralai/Mixtral-8x7B-Instruct-v0.1"],
                   free_tier=True,
                   signup_url="https://api.together.xyz/settings/api-keys")
register_provider("groq", GroqProvider, "GROQ_API_KEY",
                   display_name="Groq (Fast Inference)",
                   models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                           "mixtral-8x7b-32768"],
                   free_tier=True,
                   signup_url="https://console.groq.com/keys")
register_provider("azure_openai", AzureOpenAIProvider, "AZURE_OPENAI_API_KEY",
                   display_name="Azure OpenAI",
                   models=["gpt-4o", "gpt-4o-mini"],
                   signup_url="https://portal.azure.com/")

# Optional providers (graceful degradation if dependency missing)
try:
    from breadmind.llm.bedrock import BedrockProvider  # noqa: E402
    register_provider("bedrock", BedrockProvider, "AWS_ACCESS_KEY_ID",
                       display_name="AWS Bedrock",
                       models=["anthropic.claude-sonnet-4-6-20250514-v1:0",
                               "amazon.nova-pro-v1:0",
                               "meta.llama3-1-70b-instruct-v1:0"],
                       signup_url="https://console.aws.amazon.com/bedrock/")
except ImportError:
    pass

try:
    from breadmind.llm.litellm_provider import LiteLLMProvider  # noqa: E402
    register_provider("litellm", LiteLLMProvider, "LITELLM_API_KEY",
                       display_name="LiteLLM (Proxy/Library)",
                       models=["gpt-4o", "claude-sonnet-4-6"],
                       signup_url="https://docs.litellm.ai/")
except ImportError:
    pass
