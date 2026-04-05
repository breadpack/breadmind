"""Tests for cost display formatting."""
from __future__ import annotations

import pytest

from breadmind.cli.cost_display import (
    CostDisplay,
    ModelUsageStats,
    SessionStatus,
)


@pytest.fixture
def display():
    return CostDisplay()


@pytest.fixture
def sample_status():
    return SessionStatus(
        session_id="sess-abc123",
        current_model="claude-opus-4-20250514",
        context_usage=0.45,
        context_tokens=90_000,
        max_context=200_000,
        turns=12,
        total_cost_usd=0.0523,
        uptime_seconds=3661,
        model_stats=[
            ModelUsageStats(
                model="claude-opus-4-20250514",
                input_tokens=80_000,
                output_tokens=10_000,
                requests=12,
                estimated_cost_usd=0.0523,
                cache_hits=3,
            ),
        ],
    )


def test_format_tokens():
    assert CostDisplay.format_tokens(0) == "0"
    assert CostDisplay.format_tokens(999) == "999"
    assert CostDisplay.format_tokens(1_234) == "1.2K"
    assert CostDisplay.format_tokens(50_000) == "50.0K"
    assert CostDisplay.format_tokens(1_234_567) == "1.2M"


def test_format_cost():
    assert CostDisplay.format_cost(0) == "$0.00"
    assert CostDisplay.format_cost(0.0012) == "$0.0012"
    assert CostDisplay.format_cost(0.05) == "$0.05"
    assert CostDisplay.format_cost(1.5) == "$1.50"
    assert CostDisplay.format_cost(10.0) == "$10.00"


def test_format_duration():
    assert CostDisplay.format_duration(30) == "30s"
    assert CostDisplay.format_duration(90) == "1m 30s"
    assert CostDisplay.format_duration(3600) == "1h"
    assert CostDisplay.format_duration(3661) == "1h 1m"
    assert CostDisplay.format_duration(60) == "1m"


def test_format_status(display, sample_status):
    output = display.format_status(sample_status)
    assert "sess-abc123" in output
    assert "claude-opus-4-20250514" in output
    assert "45%" in output
    assert "90.0K" in output
    assert "12" in output
    assert "$0.05" in output
    assert "1h 1m" in output


def test_format_status_with_budget(display):
    status = SessionStatus(budget_remaining=5.0)
    output = display.format_status(status)
    assert "$5.00" in output
    assert "remaining" in output


def test_format_usage(display, sample_status):
    output = display.format_usage(sample_status)
    assert "claude-opus-4-20250514" in output
    assert "$0.05" in output
    assert "80.0K" in output
    assert "10.0K" in output


def test_format_usage_full(display, sample_status):
    output = display.format_usage(sample_status, full=True)
    assert "Context:" in output
    assert "90.0K" in output
    assert "200.0K" in output


def test_format_usage_empty(display):
    status = SessionStatus()
    output = display.format_usage(status)
    assert "No model usage" in output


def test_format_cost_footer(display):
    footer = display.format_cost_footer("claude-opus-4-20250514", 5000, 1000, 0.03)
    assert "claude-opus-4-20250514" in footer
    assert "5.0K" in footer
    assert "1.0K" in footer
    assert "$0.03" in footer


def test_toggle_footer(display):
    assert display.footer_enabled is False
    result = display.toggle_footer()
    assert result is True
    assert display.footer_enabled is True
    result = display.toggle_footer()
    assert result is False
    assert display.footer_enabled is False


def test_progress_bar():
    bar = CostDisplay._progress_bar(0.5, width=10)
    assert bar == "[#####.....]"
    bar_empty = CostDisplay._progress_bar(0.0, width=10)
    assert bar_empty == "[..........]"
    bar_full = CostDisplay._progress_bar(1.0, width=10)
    assert bar_full == "[##########]"
