"""Evaluate subagent results as normal or abnormal."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalResult:
    status: str  # "normal" | "abnormal"
    output: str
    failure_reason: str = ""
    is_timeout: bool = False


class ResultEvaluator:
    """Rule-based evaluator for subagent outputs."""

    def evaluate(self, output: str, expected_output: str) -> EvalResult:
        if not output or not output.strip():
            return EvalResult(
                status="abnormal", output=output,
                failure_reason="Empty output (expected: " + expected_output + ")",
            )
        if output.startswith("[success=False]"):
            is_timeout = "timed out" in output.lower()
            return EvalResult(
                status="abnormal", output=output,
                failure_reason=output.removeprefix("[success=False]").strip(),
                is_timeout=is_timeout,
            )
        return EvalResult(status="normal", output=output)
