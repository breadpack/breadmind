# src/breadmind/llm/router.py
from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from breadmind.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class AllProvidersFailed(Exception):
    """Every provider in the fallback chain raised; caller should downgrade."""


@dataclass
class CallMetric:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    ok: bool


class LLMRouter:
    """Cascade `providers` in order, collect per-call cost metrics.

    Intended chain (prod): Anthropic → Azure OpenAI → local Ollama (read-only).
    In tests callers inject mocks.
    """

    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        if not providers:
            raise ValueError("LLMRouter needs at least one provider")
        self._providers = list(providers)
        self._metrics: list[CallMetric] = []

    @property
    def metrics(self) -> list[CallMetric]:
        return list(self._metrics)

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            t0 = time.perf_counter()
            try:
                resp = await provider.chat(messages, tools, model)
                dt = (time.perf_counter() - t0) * 1000
                self._metrics.append(CallMetric(
                    provider=getattr(provider, "model_name", "unknown"),
                    model=model or getattr(provider, "model_name", "unknown"),
                    input_tokens=resp.usage.input_tokens,
                    output_tokens=resp.usage.output_tokens,
                    latency_ms=dt,
                    ok=True,
                ))
                return resp
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                dt = (time.perf_counter() - t0) * 1000
                self._metrics.append(CallMetric(
                    provider=getattr(provider, "model_name", "unknown"),
                    model=model or getattr(provider, "model_name", "unknown"),
                    input_tokens=0, output_tokens=0,
                    latency_ms=dt, ok=False,
                ))
                logger.warning("LLM provider %s failed: %s",
                               getattr(provider, "model_name", "?"), exc)
                continue
        raise AllProvidersFailed(str(last_error))
