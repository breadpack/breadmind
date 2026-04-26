"""Per-org monthly token ceiling for backfill (decision P1).

Atomic upsert + check pattern over the ``kb_backfill_org_budget`` table
created in migration 010. Each ``charge()`` call is a single SQL statement
that increments ``tokens_used`` and returns the post-update row, so two
concurrent callers cannot race past the ceiling.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date


class OrgMonthlyBudgetExceeded(Exception):
    """Raised when ``charge()`` would push tokens_used above tokens_ceiling."""


@dataclass
class OrgMonthlyBudget:
    """Per-org monthly token gate for KB backfill jobs.

    ``db`` is a ``breadmind.storage.database.Database`` (or any object that
    exposes asyncpg-style ``.fetchrow(query, *args)``). The default
    ``ceiling`` is used when seeding a new ``(org_id, period_month)`` row.
    """

    db: object
    ceiling: int

    async def charge(
        self,
        org_id: uuid.UUID,
        tokens: int,
        *,
        period: date,
    ) -> int:
        """Atomically charge ``tokens`` against the org's monthly budget.

        Returns the remaining tokens after the charge. Raises
        :class:`OrgMonthlyBudgetExceeded` if the charge would push usage
        above the ceiling — note: the increment still persists, so the
        caller treats the exception as a hard stop signal.
        """
        row = await self.db.fetchrow(
            """
            INSERT INTO kb_backfill_org_budget
                (org_id, period_month, tokens_used, tokens_ceiling)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (org_id, period_month) DO UPDATE
                SET tokens_used = kb_backfill_org_budget.tokens_used
                                  + EXCLUDED.tokens_used,
                    updated_at = now()
            RETURNING tokens_used, tokens_ceiling
            """,
            org_id,
            period,
            tokens,
            self.ceiling,
        )
        used = row["tokens_used"]
        ceiling = row["tokens_ceiling"]
        if used > ceiling:
            raise OrgMonthlyBudgetExceeded(
                f"org {org_id} {period:%Y-%m} exceeded monthly token "
                f"ceiling ({used}/{ceiling})"
            )
        return ceiling - used

    async def remaining(
        self,
        org_id: uuid.UUID,
        *,
        period: date,
    ) -> int:
        """Return remaining tokens for ``(org_id, period)``.

        If no row exists yet, returns the configured default ``ceiling``.
        """
        row = await self.db.fetchrow(
            """
            SELECT tokens_used, tokens_ceiling
            FROM kb_backfill_org_budget
            WHERE org_id = $1 AND period_month = $2
            """,
            org_id,
            period,
        )
        if row is None:
            return self.ceiling
        return row["tokens_ceiling"] - row["tokens_used"]
