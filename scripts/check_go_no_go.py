"""Programmatic Phase-1 -> Phase-2 gating check (spec §9.5).

Usage:
    python scripts/check_go_no_go.py --report path/to/report.json

Exit code:
    0 if GO
    1 if NO_GO
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Sequence


@dataclass
class Check:
    name: str
    value: float
    target: float
    comparator: str
    passed: bool


@dataclass
class GoNoGoReport:
    decision: str
    checks: list[Check]


_TARGETS: list[tuple[str, float, str]] = [
    ("recall_at_5",                 0.80, ">="),
    ("citation_accuracy",           0.95, ">="),
    ("hallucination_rate",          0.03, "<="),
    ("sensitive_block_precision",   0.90, ">="),
    ("user_satisfaction",           0.75, ">="),
    ("weekly_active_users_ratio",   0.70, ">="),
    ("security_incidents",          0.0,  "=="),
    ("p95_latency_seconds",         6.0,  "<="),
    ("review_queue_processed_ratio", 0.80, ">="),
]


def _compare(value: float, target: float, op: str) -> bool:
    if op == ">=": return value >= target
    if op == "<=": return value <= target
    if op == "==": return value == target
    raise ValueError(op)


def evaluate(**m: float) -> GoNoGoReport:
    checks = [
        Check(name=n, value=float(m[n]), target=t, comparator=op,
              passed=_compare(float(m[n]), t, op))
        for (n, t, op) in _TARGETS
    ]
    decision = "GO" if all(c.passed for c in checks) else "NO_GO"
    return GoNoGoReport(decision=decision, checks=checks)


def _render(report: GoNoGoReport) -> str:
    lines = [f"Decision: {report.decision}"]
    for c in report.checks:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"  [{mark}] {c.name} = {c.value} (target {c.comparator} {c.target})")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True,
                    help="Path to JSON file with metric keys (see _TARGETS)")
    args = ap.parse_args(argv)
    data = json.loads(open(args.report, encoding="utf-8").read())
    report = evaluate(**data)
    print(_render(report))
    sys.exit(0 if report.decision == "GO" else 1)


if __name__ == "__main__":
    main()
