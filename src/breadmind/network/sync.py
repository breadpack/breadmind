"""Offline sync reconciliation with idempotency."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Statuses that count as "resolved" (no longer accept updates)
_FINAL_STATUSES = {"success", "failure", "escalated"}


class SyncManager:
    """Reconciles task results using accept-first-wins policy."""

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}  # idempotency_key -> result

    def reconcile(self, idempotency_key: str, result: dict) -> bool:
        """Accept result if no final result exists for this key. Returns True if accepted."""
        existing = self._results.get(idempotency_key)
        if existing and existing.get("status") in _FINAL_STATUSES:
            logger.info(
                "Duplicate result for %s (existing: %s, new: %s) — rejected",
                idempotency_key, existing.get("status"), result.get("status"),
            )
            return False
        self._results[idempotency_key] = result
        return True

    def bulk_reconcile(self, results: list[dict]) -> tuple[int, int]:
        """Reconcile multiple results. Returns (accepted_count, rejected_count)."""
        accepted = 0
        rejected = 0
        for r in results:
            key = r.get("idempotency_key", r.get("task_id", ""))
            if self.reconcile(key, r):
                accepted += 1
            else:
                rejected += 1
        return accepted, rejected

    def get_result(self, idempotency_key: str) -> dict | None:
        return self._results.get(idempotency_key)
