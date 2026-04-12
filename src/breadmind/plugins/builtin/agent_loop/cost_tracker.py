"""세션별 비용 추적."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

_PRICING_FILE = Path(__file__).resolve().parents[5] / "config" / "model_pricing.yaml"

# 모델별 가격 (USD / 1M tokens) — YAML 로드 실패 시 폴백
_FALLBACK_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.0,
        "cache_creation": 1.0,
        "cache_read": 0.08,
    },
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_creation": 18.75,
        "cache_read": 1.50,
    },
    "gemini-2.5-flash": {
        "input": 0.15,
        "output": 0.60,
    },
    "gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.0,
    },
    "grok-3": {
        "input": 3.0,
        "output": 15.0,
    },
    "grok-3-mini": {
        "input": 0.30,
        "output": 0.50,
    },
}


def _load_pricing() -> dict[str, dict[str, float]]:
    try:
        if _PRICING_FILE.exists():
            with open(_PRICING_FILE, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and 'models' in data:
                return {
                    model_name: model_config.get('pricing', {})
                    for model_name, model_config in data['models'].items()
                }
            return data
    except Exception:
        pass
    return _FALLBACK_PRICING


MODEL_PRICING: dict[str, dict[str, float]] = _load_pricing()


@dataclass
class UsageSnapshot:
    """특정 시점의 사용량 스냅샷."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0


@dataclass
class CostTracker:
    """세션별 비용 추적."""

    model: str = "claude-sonnet-4-6"
    _total_input: int = 0
    _total_output: int = 0
    _total_cache_creation: int = 0
    _total_cache_read: int = 0
    _total_cost: float = 0.0
    _api_calls: int = 0
    _session_start: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation: int = 0,
        cache_read: int = 0,
        model: str | None = None,
    ) -> float:
        """API 호출 결과 기록. 이번 호출의 비용(USD)을 반환한다."""
        self._total_input += input_tokens
        self._total_output += output_tokens
        self._total_cache_creation += cache_creation
        self._total_cache_read += cache_read
        self._api_calls += 1

        use_model = model or self.model
        pricing = MODEL_PRICING.get(use_model, {})
        per_m = 1_000_000.0

        call_cost = (
            input_tokens * pricing.get("input", 0) / per_m
            + output_tokens * pricing.get("output", 0) / per_m
            + cache_creation * pricing.get("cache_creation", 0) / per_m
            + cache_read * pricing.get("cache_read", 0) / per_m
        )
        self._total_cost += call_cost
        return call_cost

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def total_tokens(self) -> int:
        return self._total_input + self._total_output

    @property
    def api_calls(self) -> int:
        return self._api_calls

    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            input_tokens=self._total_input,
            output_tokens=self._total_output,
            cache_creation_tokens=self._total_cache_creation,
            cache_read_tokens=self._total_cache_read,
            cost_usd=self._total_cost,
            api_calls=self._api_calls,
        )

    def format_summary(self) -> str:
        """사람이 읽기 쉬운 요약."""
        s = self.snapshot()
        cost_str = (
            f"${s.cost_usd:.4f}" if s.cost_usd < 0.01 else f"${s.cost_usd:.2f}"
        )
        return (
            f"{s.input_tokens:,} in / {s.output_tokens:,} out "
            f"({s.api_calls} calls) = {cost_str}"
        )
