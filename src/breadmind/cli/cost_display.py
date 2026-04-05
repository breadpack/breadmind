"""Cost visibility: display session cost, model usage, and context stats."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ModelUsageStats:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    estimated_cost_usd: float = 0.0
    cache_hits: int = 0


@dataclass
class SessionStatus:
    session_id: str = ""
    current_model: str = ""
    context_usage: float = 0.0  # 0.0-1.0
    context_tokens: int = 0
    max_context: int = 200_000
    turns: int = 0
    total_cost_usd: float = 0.0
    budget_remaining: float | None = None
    model_stats: list[ModelUsageStats] = field(default_factory=list)
    uptime_seconds: float = 0.0


class CostDisplay:
    """Formats and displays cost/usage information.

    Provides:
    - /status: Quick session overview (model, context, cost)
    - /usage: Detailed per-model breakdown
    - /usage full: Append cost footer to every response
    """

    def __init__(self) -> None:
        self._append_footer = False
        self._session_start: float = time.time()

    def format_status(self, status: SessionStatus) -> str:
        """Format /status output as readable text."""
        ctx_pct = status.context_usage * 100
        ctx_bar = self._progress_bar(status.context_usage)
        lines = [
            f"Session: {status.session_id or '(none)'}",
            f"Model:   {status.current_model or '(not set)'}",
            f"Context: {ctx_bar} {ctx_pct:.0f}% "
            f"({self.format_tokens(status.context_tokens)}/{self.format_tokens(status.max_context)})",
            f"Turns:   {status.turns}",
            f"Cost:    {self.format_cost(status.total_cost_usd)}",
            f"Uptime:  {self.format_duration(status.uptime_seconds)}",
        ]
        if status.budget_remaining is not None:
            lines.append(f"Budget:  {self.format_cost(status.budget_remaining)} remaining")
        return "\n".join(lines)

    def format_usage(self, status: SessionStatus, full: bool = False) -> str:
        """Format /usage output with optional per-model detail."""
        lines = [
            f"Total cost: {self.format_cost(status.total_cost_usd)}",
            f"Total turns: {status.turns}",
            "",
        ]

        if status.model_stats:
            lines.append("Per-model breakdown:")
            lines.append(f"  {'Model':<30} {'Reqs':>6} {'In':>8} {'Out':>8} {'Cache':>6} {'Cost':>10}")
            lines.append("  " + "-" * 72)
            for ms in status.model_stats:
                lines.append(
                    f"  {ms.model:<30} {ms.requests:>6} "
                    f"{self.format_tokens(ms.input_tokens):>8} "
                    f"{self.format_tokens(ms.output_tokens):>8} "
                    f"{ms.cache_hits:>6} "
                    f"{self.format_cost(ms.estimated_cost_usd):>10}"
                )
        else:
            lines.append("No model usage recorded yet.")

        if full:
            lines.append("")
            lines.append(
                f"Context: {self.format_tokens(status.context_tokens)} / "
                f"{self.format_tokens(status.max_context)} "
                f"({status.context_usage * 100:.0f}%)"
            )

        return "\n".join(lines)

    def format_cost_footer(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> str:
        """Format a compact cost footer for appending to responses."""
        return (
            f"[{model} | in:{self.format_tokens(input_tokens)} "
            f"out:{self.format_tokens(output_tokens)} | "
            f"{self.format_cost(cost)}]"
        )

    def toggle_footer(self) -> bool:
        """Toggle per-response cost footer.  Returns new state."""
        self._append_footer = not self._append_footer
        return self._append_footer

    @property
    def footer_enabled(self) -> bool:
        return self._append_footer

    # ------------------------------------------------------------------
    # Static formatters
    # ------------------------------------------------------------------

    @staticmethod
    def format_tokens(n: int) -> str:
        """Format token count (e.g., 1234 -> '1.2K', 1234567 -> '1.2M')."""
        if n < 1_000:
            return str(n)
        if n < 1_000_000:
            return f"{n / 1_000:.1f}K"
        return f"{n / 1_000_000:.1f}M"

    @staticmethod
    def format_cost(usd: float) -> str:
        """Format cost (e.g., 0.0234 -> '$0.0234', 1.5 -> '$1.50')."""
        if usd == 0:
            return "$0.00"
        if usd < 0.01:
            return f"${usd:.4f}"
        return f"${usd:.2f}"

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Format duration (e.g., 3661 -> '1h 1m')."""
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = int(seconds) // 60
        if minutes < 60:
            secs = int(seconds) % 60
            return f"{minutes}m {secs}s" if secs else f"{minutes}m"
        hours = minutes // 60
        remaining_mins = minutes % 60
        if remaining_mins:
            return f"{hours}h {remaining_mins}m"
        return f"{hours}h"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _progress_bar(fraction: float, width: int = 20) -> str:
        filled = int(fraction * width)
        filled = max(0, min(width, filled))
        return "[" + "#" * filled + "." * (width - filled) + "]"
