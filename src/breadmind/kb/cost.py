"""Cost constants and estimator used by alert rules and quality reports.

The Prometheus alert rule `HighTokenCost` multiplies
`breadmind_llm_tokens_total` by these constants to flag >120% of budget.
"""
from __future__ import annotations

from typing import Mapping

PRICE_PER_1K: dict[tuple[str, str], float] = {
    ("anthropic", "input"): 3.0,
    ("anthropic", "output"): 15.0,
    ("azure", "input"): 2.5,
    ("azure", "output"): 10.0,
    ("ollama", "input"): 0.0,
    ("ollama", "output"): 0.0,
}

DAILY_BUDGET_USD: float = 50.0


def estimate_daily_cost_usd(
    token_counts: Mapping[tuple[str, str], int],
) -> float:
    """Sum (tokens/1000) * price over all (provider, direction) pairs."""
    total = 0.0
    for (provider, direction), count in token_counts.items():
        price = PRICE_PER_1K.get((provider, direction), 0.0)
        total += (count / 1000.0) * price
    return total
