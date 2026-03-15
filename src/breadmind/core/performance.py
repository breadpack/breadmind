from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)

_MAX_RECENT_RECORDS = 100


@dataclass
class TaskRecord:
    role: str
    task_description: str
    success: bool
    duration_ms: float
    result_summary: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RoleStats:
    role: str
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    recent_records: list[TaskRecord] = field(default_factory=list)
    feedback_history: list[dict] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.successes / self.total_runs

    @property
    def avg_duration_ms(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_duration_ms / self.total_runs


class PerformanceTracker:
    """Tracks execution performance of swarm roles and skills."""

    def __init__(self, db: Database | None = None):
        self._db = db
        self._stats: dict[str, RoleStats] = {}
        self._lock = asyncio.Lock()

    async def record_task_result(
        self, role: str, task_desc: str, success: bool,
        duration_ms: float, result_summary: str,
    ) -> None:
        async with self._lock:
            stats = self._stats.setdefault(role, RoleStats(role=role))
            stats.total_runs += 1
            if success:
                stats.successes += 1
            else:
                stats.failures += 1
            stats.total_duration_ms += duration_ms
            record = TaskRecord(role=role, task_description=task_desc, success=success,
                                duration_ms=duration_ms, result_summary=result_summary)
            stats.recent_records.append(record)
            if len(stats.recent_records) > _MAX_RECENT_RECORDS:
                stats.recent_records = stats.recent_records[-_MAX_RECENT_RECORDS:]

    async def record_feedback(self, role: str, rating: str, comment: str) -> None:
        async with self._lock:
            stats = self._stats.setdefault(role, RoleStats(role=role))
            stats.feedback_history.append({
                "rating": rating, "comment": comment,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def get_role_stats(self, role: str) -> RoleStats | None:
        return self._stats.get(role)

    def get_all_stats(self) -> dict[str, RoleStats]:
        return dict(self._stats)

    def get_underperforming_roles(self, threshold: float = 0.5) -> list[RoleStats]:
        return [s for s in self._stats.values() if s.total_runs > 0 and s.success_rate < threshold]

    def get_top_roles(self, limit: int = 5) -> list[RoleStats]:
        ranked = sorted(
            [s for s in self._stats.values() if s.total_runs > 0],
            key=lambda s: (s.success_rate, s.total_runs), reverse=True,
        )
        return ranked[:limit]

    async def suggest_improvements(self, role: str, message_handler) -> str:
        stats = self._stats.get(role)
        if not stats or stats.total_runs == 0:
            return f"No data available for role '{role}'."
        failures = [r for r in stats.recent_records if not r.success]
        if not failures:
            return f"Role '{role}' has no recent failures."
        failure_summaries = "\n".join(
            f"- Task: {r.task_description} | Error: {r.result_summary}" for r in failures[:10]
        )
        prompt = (
            f"Analyze failure patterns for the '{role}' role.\n\n"
            f"Stats: {stats.total_runs} total, {stats.successes} successes, "
            f"{stats.failures} failures ({stats.success_rate:.0%} success rate)\n\n"
            f"Recent failures:\n{failure_summaries}\n\n"
            f"Suggest specific improvements to the role's system prompt to reduce failures. Be concise and actionable."
        )
        try:
            if asyncio.iscoroutinefunction(message_handler):
                return await message_handler(prompt, user="performance_tracker", channel="system:performance")
            return message_handler(prompt, user="performance_tracker", channel="system:performance")
        except Exception as e:
            logger.error(f"Failed to generate improvement suggestions: {e}")
            return f"Error generating suggestions: {e}"

    def export_stats(self) -> dict:
        result = {}
        for role, stats in self._stats.items():
            result[role] = {
                "total_runs": stats.total_runs, "successes": stats.successes,
                "failures": stats.failures, "total_duration_ms": stats.total_duration_ms,
                "feedback_history": stats.feedback_history,
            }
        return result

    def import_stats(self, data: dict) -> None:
        self._stats.clear()
        for role, d in data.items():
            self._stats[role] = RoleStats(
                role=role, total_runs=d.get("total_runs", 0),
                successes=d.get("successes", 0), failures=d.get("failures", 0),
                total_duration_ms=d.get("total_duration_ms", 0.0),
                feedback_history=d.get("feedback_history", []),
            )

    async def flush_to_db(self) -> None:
        if self._db:
            try:
                await self._db.set_setting("performance_stats", self.export_stats())
            except Exception as e:
                logger.error(f"Failed to flush performance stats: {e}")

    async def load_from_db(self) -> None:
        if self._db:
            try:
                data = await self._db.get_setting("performance_stats")
                if data:
                    self.import_stats(data)
            except Exception as e:
                logger.error(f"Failed to load performance stats: {e}")
