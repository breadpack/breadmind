"""Scripted LLM provider stub: deterministic outputs per (marker_in_prompt).

Tests drive the stub by setting `script` entries; if no matcher hits, the
provider emits a canned 'no-evidence' answer. `fail_mode` simulates outage.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Usage:
    input_tokens: int = 50
    output_tokens: int = 25


@dataclass
class StubLLM:
    provider: str = "anthropic"
    model: str = "claude-opus"
    fail_mode: str = ""
    script: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def complete(self, prompt: str, hits: list) -> tuple[object, Usage]:
        self.calls.append((self.provider, prompt))
        if self.fail_mode == "down":
            raise RuntimeError("provider down")
        for key, answer in self.script.items():
            if key in prompt:
                return _Draft(answer, [h.id for h in hits][:2]), Usage()
        return _Draft("근거 부족", []), Usage()


@dataclass
class _Draft:
    text: str
    citation_ids: list[str]
    preliminary_confidence: str = "high"


class FallbackRouter:
    """Ordered provider list. `.complete()` cycles until one succeeds."""

    def __init__(self, providers: list[StubLLM]) -> None:
        assert providers
        self._providers = providers
        self.provider = providers[0].provider
        self.model = providers[0].model

    async def complete(self, prompt: str, hits: list):
        last: Exception | None = None
        for p in self._providers:
            try:
                self.provider = p.provider
                self.model = p.model
                return await p.complete(prompt, hits)
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(f"all providers failed: {last}")
