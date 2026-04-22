"""CredentialVault smoke check: every required credential id resolvable."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus

_REQUIRED_IDS = ("slack_bot_token", "slack_app_token", "confluence_token")


@dataclass
class VaultCheck:
    vault: Any  # CredentialVault (duck-typed for testability)
    name: str = "vault"
    depends_on: list[str] = field(default_factory=lambda: ["config"])

    async def run(self, targets: Any, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        missing: list[str] = []
        for cid in _REQUIRED_IDS:
            try:
                value = await self.vault.retrieve(cid)
            except Exception as exc:  # noqa: BLE001
                return CheckOutcome(
                    name=self.name, status=CheckStatus.FAIL,
                    detail=redact_secrets(f"vault error on {cid}: {exc}"),
                    duration_ms=int((perf_counter() - t0) * 1000),
                )
            if not value:
                missing.append(cid)
        if missing:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"missing credentials: {', '.join(missing)}",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"{len(_REQUIRED_IDS)} credentials present",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
