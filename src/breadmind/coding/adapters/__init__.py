from __future__ import annotations

from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult
from breadmind.coding.adapters.claude_code import ClaudeCodeAdapter
from breadmind.coding.adapters.codex import CodexAdapter
from breadmind.coding.adapters.gemini_cli import GeminiCLIAdapter

_ADAPTERS: dict[str, CodingAgentAdapter] = {
    "claude": ClaudeCodeAdapter(),
    "codex": CodexAdapter(),
    "gemini": GeminiCLIAdapter(),
}


def get_adapter(name: str) -> CodingAgentAdapter:
    if name not in _ADAPTERS:
        raise ValueError(
            f"Unknown coding agent: {name}. Available: {list(_ADAPTERS.keys())}"
        )
    return _ADAPTERS[name]


__all__ = [
    "CodingAgentAdapter",
    "CodingResult",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "GeminiCLIAdapter",
    "get_adapter",
]
