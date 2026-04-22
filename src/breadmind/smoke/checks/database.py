"""Database smoke check: DSN reachable + alembic_version matches head."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from time import perf_counter

import asyncpg

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets


@dataclass
class DatabaseCheck:
    name: str = "database"
    depends_on: list[str] = field(default_factory=lambda: ["config"])

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="DATABASE_URL not set",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        try:
            conn = await asyncio.wait_for(asyncpg.connect(dsn=dsn), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=redact_secrets(
                    "timeout" if isinstance(exc, asyncio.TimeoutError) else str(exc),
                ),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        try:
            try:
                current = await asyncio.wait_for(
                    conn.fetchval(
                        "SELECT version_num FROM alembic_version LIMIT 1",
                    ),
                    timeout=timeout,
                )
            except Exception as exc:  # noqa: BLE001
                return CheckOutcome(
                    name=self.name, status=CheckStatus.FAIL,
                    detail=redact_secrets(
                        "timeout" if isinstance(exc, asyncio.TimeoutError) else str(exc),
                    ),
                    duration_ms=int((perf_counter() - t0) * 1000),
                )
        finally:
            await conn.close()

        if current != targets.migration_head:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=(
                    f"migration head mismatch: db={current} "
                    f"expected={targets.migration_head} "
                    f"(run `breadmind migrate upgrade`)"
                ),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"head={current}",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
