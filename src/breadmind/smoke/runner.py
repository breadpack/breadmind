"""Orchestration: runs every SmokeCheck respecting depends_on, aggregates."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Iterable, Protocol

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus


class ExitCode(IntEnum):
    GO = 0
    NO_GO = 1
    CONFIG_ERROR = 2


class _SmokeCheck(Protocol):
    name: str
    depends_on: list[str]

    async def run(self, targets: Any, timeout: float) -> CheckOutcome: ...


@dataclass
class SmokeRunner:
    checks: list[_SmokeCheck]
    targets: Any
    timeout: float = 5.0
    skip: set[str] = field(default_factory=set)
    progress: Any = None            # writable stream; default stderr at module boundary

    async def run(self) -> tuple[ExitCode, list[CheckOutcome]]:
        names = [c.name for c in self.checks]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                f"duplicate smoke check names: {', '.join(dupes)}",
            )
        outcomes: dict[str, CheckOutcome] = {}
        pending = {c.name: c for c in self.checks}
        order = [c.name for c in self.checks]

        stream = self.progress if self.progress is not None else sys.stderr

        async def _execute(check: _SmokeCheck) -> CheckOutcome:
            if check.name in self.skip:
                return CheckOutcome(
                    name=check.name, status=CheckStatus.SKIP,
                    detail="--skip flag",
                )
            failed_deps = [
                d for d in check.depends_on
                if d in outcomes and outcomes[d].status is not CheckStatus.PASS
            ]
            if failed_deps:
                return CheckOutcome(
                    name=check.name, status=CheckStatus.SKIP,
                    detail=f"dependency {failed_deps[0]} not pass",
                )
            try:
                return await check.run(self.targets, self.timeout)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return CheckOutcome(
                    name=check.name, status=CheckStatus.FAIL,
                    detail=(
                        f"runner exception: {type(exc).__name__}: "
                        f"{redact_secrets(str(exc))}"
                    ),
                )

        total = len(self.checks)
        done = 0
        while pending:
            ready = [
                c for c in pending.values()
                if all(d in outcomes for d in c.depends_on)
            ]
            if not ready:
                for c in pending.values():
                    outcomes[c.name] = CheckOutcome(
                        name=c.name, status=CheckStatus.SKIP,
                        detail="unresolved dependency",
                    )
                break

            results = await asyncio.gather(
                *(_execute(c) for c in ready), return_exceptions=False,
            )
            for c, outcome in zip(ready, results):
                outcomes[c.name] = outcome
                pending.pop(c.name, None)
                done += 1
                stream.write(
                    f"[{done}/{total}] {outcome.name} … "
                    f"{outcome.status.value} "
                    f"{redact_secrets(outcome.detail)[:120]}\n",
                )
                stream.flush()

        ordered = [outcomes[n] for n in order]
        if outcomes.get("config") and outcomes["config"].status is CheckStatus.FAIL:
            return ExitCode.CONFIG_ERROR, ordered
        if any(o.status is CheckStatus.FAIL for o in ordered):
            return ExitCode.NO_GO, ordered
        return ExitCode.GO, ordered


def render_table(outcomes: Iterable[CheckOutcome]) -> str:
    rows = list(outcomes)
    name_w = max((len(o.name) for o in rows), default=4)
    out_lines = [f"{'CHECK'.ljust(name_w)}  STATUS  MS    DETAIL"]
    out_lines.append("-" * (name_w + 30))
    for o in rows:
        out_lines.append(
            f"{o.name.ljust(name_w)}  {o.status.value.ljust(4)}    "
            f"{str(o.duration_ms).rjust(5)}  {redact_secrets(o.detail)}",
        )
    summary = {
        "pass": sum(1 for o in rows if o.status is CheckStatus.PASS),
        "fail": sum(1 for o in rows if o.status is CheckStatus.FAIL),
        "skip": sum(1 for o in rows if o.status is CheckStatus.SKIP),
    }
    out_lines.append("")
    out_lines.append(
        f"PASS={summary['pass']}  FAIL={summary['fail']}  SKIP={summary['skip']}",
    )
    return "\n".join(out_lines)
