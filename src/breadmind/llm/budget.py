"""Budget manager -- tracks cumulative spend and enforces limits.

Tracks daily/monthly costs per provider with configurable alerts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


@dataclass
class BudgetConfig:
    """Budget limits and alert configuration."""
    daily_limit: float = 10.0           # USD per day
    monthly_limit: float = 200.0        # USD per month
    per_provider_daily: float = 5.0     # USD per provider per day
    alert_thresholds: list[float] = field(default_factory=lambda: [0.5, 0.8, 0.95])
    auto_downgrade: bool = True         # Auto-downgrade tier when approaching limits


@dataclass
class _PeriodUsage:
    """Usage tracking for a single period (day or month)."""
    total: float = 0.0
    by_provider: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    request_count: int = 0


class BudgetManager:
    """Tracks cumulative spend and enforces daily/monthly limits."""

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self._config = config or BudgetConfig()
        self._daily: _PeriodUsage = _PeriodUsage()
        self._monthly: _PeriodUsage = _PeriodUsage()
        self._current_day: date = date.today()
        self._current_month: tuple[int, int] = (date.today().year, date.today().month)
        self._alerted_daily: set[float] = set()
        self._alerted_monthly: set[float] = set()

    def _maybe_rollover(self) -> None:
        """Reset period counters if the day or month changed."""
        today = date.today()
        if today != self._current_day:
            self._daily = _PeriodUsage()
            self._current_day = today
            self._alerted_daily.clear()
        current_ym = (today.year, today.month)
        if current_ym != self._current_month:
            self._monthly = _PeriodUsage()
            self._current_month = current_ym
            self._alerted_monthly.clear()

    def record_cost(self, provider: str, model: str, cost_usd: float) -> None:
        """Record a cost event."""
        self._maybe_rollover()
        self._daily.total += cost_usd
        self._daily.by_provider[provider] = self._daily.by_provider.get(provider, 0.0) + cost_usd
        self._daily.by_model[model] = self._daily.by_model.get(model, 0.0) + cost_usd
        self._daily.request_count += 1

        self._monthly.total += cost_usd
        self._monthly.by_provider[provider] = self._monthly.by_provider.get(provider, 0.0) + cost_usd
        self._monthly.by_model[model] = self._monthly.by_model.get(model, 0.0) + cost_usd
        self._monthly.request_count += 1

    def can_afford(self, provider: str, estimated_cost: float) -> bool:
        """Check if spending estimated_cost would stay within budget."""
        self._maybe_rollover()
        if self._daily.total + estimated_cost > self._config.daily_limit:
            return False
        if self._monthly.total + estimated_cost > self._config.monthly_limit:
            return False
        provider_usage = self._daily.by_provider.get(provider, 0.0)
        if provider_usage + estimated_cost > self._config.per_provider_daily:
            return False
        return True

    def get_usage_summary(self) -> dict:
        """Return current usage summary."""
        self._maybe_rollover()
        return {
            "daily": {
                "total": round(self._daily.total, 6),
                "limit": self._config.daily_limit,
                "remaining": round(max(0, self._config.daily_limit - self._daily.total), 6),
                "by_provider": dict(self._daily.by_provider),
                "by_model": dict(self._daily.by_model),
                "request_count": self._daily.request_count,
            },
            "monthly": {
                "total": round(self._monthly.total, 6),
                "limit": self._config.monthly_limit,
                "remaining": round(max(0, self._config.monthly_limit - self._monthly.total), 6),
                "by_provider": dict(self._monthly.by_provider),
                "by_model": dict(self._monthly.by_model),
                "request_count": self._monthly.request_count,
            },
        }

    def check_alerts(self) -> list[str]:
        """Check for budget alert thresholds and return alert messages.

        Each threshold is reported at most once per period.
        """
        self._maybe_rollover()
        alerts: list[str] = []

        for threshold in self._config.alert_thresholds:
            # Daily alerts
            if threshold not in self._alerted_daily:
                ratio = self._daily.total / self._config.daily_limit if self._config.daily_limit > 0 else 0
                if ratio >= threshold:
                    pct = int(threshold * 100)
                    alerts.append(
                        f"Daily budget {pct}% reached: ${self._daily.total:.4f} / ${self._config.daily_limit:.2f}"
                    )
                    self._alerted_daily.add(threshold)

            # Monthly alerts
            if threshold not in self._alerted_monthly:
                ratio = self._monthly.total / self._config.monthly_limit if self._config.monthly_limit > 0 else 0
                if ratio >= threshold:
                    pct = int(threshold * 100)
                    alerts.append(
                        f"Monthly budget {pct}% reached: ${self._monthly.total:.4f} / ${self._config.monthly_limit:.2f}"
                    )
                    self._alerted_monthly.add(threshold)

        return alerts

    @property
    def auto_downgrade(self) -> bool:
        """Whether automatic tier downgrade is enabled."""
        return self._config.auto_downgrade

    @property
    def config(self) -> BudgetConfig:
        return self._config
