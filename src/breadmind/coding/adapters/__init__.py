from __future__ import annotations

from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult
from breadmind.coding.adapters.claude_code import ClaudeCodeAdapter
from breadmind.coding.adapters.gemini_cli import GeminiCLIAdapter

# Populated by the plugin system at boot; empty by default so that
# only plugin-registered adapters are active.
_ADAPTERS: dict = {}

# Hardcoded classes kept as fallback when the plugin system hasn't loaded yet.
_FALLBACK_ADAPTERS = {
    "claude": ClaudeCodeAdapter,
    "gemini": GeminiCLIAdapter,
}


def get_adapter(name: str) -> CodingAgentAdapter:
    if name in _ADAPTERS:
        return _ADAPTERS[name]
    # Fallback to hardcoded if plugins haven't loaded
    if name in _FALLBACK_ADAPTERS:
        return _FALLBACK_ADAPTERS[name]()
    raise ValueError(
        f"Unknown coding agent: {name}. Available: "
        f"{list(set(list(_ADAPTERS.keys()) + list(_FALLBACK_ADAPTERS.keys())))}"
    )


def register_adapter(name: str, adapter: CodingAgentAdapter) -> None:
    _ADAPTERS[name] = adapter


def unregister_adapter(name: str) -> None:
    _ADAPTERS.pop(name, None)


__all__ = [
    "CodingAgentAdapter",
    "CodingResult",
    "ClaudeCodeAdapter",
    "GeminiCLIAdapter",
    "get_adapter",
    "register_adapter",
    "unregister_adapter",
]
