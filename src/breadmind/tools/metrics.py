from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
import asyncio


@dataclass
class ToolMetrics:
    total_calls: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    total_duration_ms: float = 0
    last_called: datetime | None = None


class MetricsCollector:
    """Collect and report tool execution metrics."""

    def __init__(self):
        self._metrics: dict[str, ToolMetrics] = defaultdict(ToolMetrics)
        self._lock = asyncio.Lock()

    async def record(self, tool_name: str, success: bool, duration_ms: float,
                     timed_out: bool = False):
        async with self._lock:
            m = self._metrics[tool_name]
            m.total_calls += 1
            m.total_duration_ms += duration_ms
            m.last_called = datetime.now(timezone.utc)
            if timed_out:
                m.timeout_count += 1
            if success:
                m.success_count += 1
            else:
                m.error_count += 1

    def get_metrics(self, tool_name: str | None = None) -> dict:
        """Get metrics for a specific tool or all tools."""
        if tool_name is not None:
            m = self._metrics.get(tool_name)
            if m is None:
                return {}
            return {
                "total_calls": m.total_calls,
                "success_count": m.success_count,
                "error_count": m.error_count,
                "timeout_count": m.timeout_count,
                "total_duration_ms": m.total_duration_ms,
                "avg_duration_ms": m.total_duration_ms / m.total_calls if m.total_calls else 0,
                "last_called": m.last_called.isoformat() if m.last_called else None,
            }
        return {name: self.get_metrics(name) for name in self._metrics}

    def get_summary(self) -> dict:
        """Get summary: total calls, avg latency, error rate, most used tools."""
        total_calls = sum(m.total_calls for m in self._metrics.values())
        total_duration = sum(m.total_duration_ms for m in self._metrics.values())
        total_errors = sum(m.error_count for m in self._metrics.values())

        avg_latency = total_duration / total_calls if total_calls else 0
        error_rate = total_errors / total_calls if total_calls else 0

        most_used = sorted(
            self._metrics.items(),
            key=lambda item: item[1].total_calls,
            reverse=True,
        )
        most_used_tools = [
            {"name": name, "calls": m.total_calls}
            for name, m in most_used[:5]
        ]

        return {
            "total_calls": total_calls,
            "avg_latency_ms": avg_latency,
            "error_rate": error_rate,
            "most_used_tools": most_used_tools,
        }

    def reset(self):
        self._metrics.clear()
