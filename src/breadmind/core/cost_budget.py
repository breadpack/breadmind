"""Per-session cost budget management."""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class CostEntry:
    """A single token-usage record."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    turn: int = 0


class BudgetExhaustedError(Exception):
    """Raised when the session cost budget is exceeded."""

    def __init__(self, spent: float, budget: float) -> None:
        self.spent = spent
        self.budget = budget
        super().__init__(
            f"Budget exhausted: ${spent:.4f} spent of ${budget:.2f} limit"
        )


class CostBudget:
    """Per-session cost budget manager.

    Tracks spending and enforces dollar limits.
    When budget is exhausted, raises :class:`BudgetExhaustedError`.
    """

    # Approximate costs per 1M tokens (input, output)
    MODEL_COSTS: dict[str, tuple[float, float]] = {
        "claude-opus-4-6": (15.0, 75.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-haiku-4-5": (0.80, 4.0),
        "gemini-2.5-flash": (0.15, 0.60),
        "gemini-2.5-pro": (1.25, 10.0),
        "grok-3": (3.0, 15.0),
    }

    def __init__(self, max_budget_usd: float | None = None) -> None:
        self._max_budget = max_budget_usd
        self._entries: list[CostEntry] = []
        self._total_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def remaining(self) -> float | None:
        """Remaining budget in USD, or ``None`` if no budget is set."""
        if self._max_budget is None:
            return None
        return max(0.0, self._max_budget - self._total_cost)

    @property
    def is_exhausted(self) -> bool:
        if self._max_budget is None:
            return False
        return self._total_cost >= self._max_budget

    @property
    def entries(self) -> list[CostEntry]:
        return list(self._entries)

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        turn: int = 0,
    ) -> CostEntry:
        """Record token usage and calculate cost."""
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        entry = CostEntry(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            turn=turn,
        )
        self._entries.append(entry)
        self._total_cost += cost
        return entry

    def estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Estimate cost for given usage without recording."""
        input_rate, output_rate = self.MODEL_COSTS.get(model, (0.0, 0.0))
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    def check_budget(self) -> None:
        """Raise :class:`BudgetExhaustedError` if budget is exceeded."""
        if self._max_budget is not None and self._total_cost >= self._max_budget:
            raise BudgetExhaustedError(self._total_cost, self._max_budget)

    def summary(self) -> dict:
        """Return cost summary with per-model breakdown."""
        per_model: dict[str, dict] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
        )
        for entry in self._entries:
            m = per_model[entry.model]
            m["input_tokens"] += entry.input_tokens
            m["output_tokens"] += entry.output_tokens
            m["cost_usd"] += entry.cost_usd
            m["calls"] += 1

        return {
            "total_cost_usd": self._total_cost,
            "max_budget_usd": self._max_budget,
            "remaining_usd": self.remaining,
            "total_entries": len(self._entries),
            "per_model": dict(per_model),
        }

    @classmethod
    def from_env(cls) -> CostBudget:
        """Create from ``BREADMIND_MAX_BUDGET_USD`` env var."""
        budget = os.environ.get("BREADMIND_MAX_BUDGET_USD")
        return cls(float(budget) if budget else None)
