"""Tests for effort level control."""
from __future__ import annotations

import os
from unittest.mock import patch

from breadmind.llm.effort import EffortConfig, EffortLevel, EffortManager


async def test_default_level():
    mgr = EffortManager()
    assert mgr.level == EffortLevel.MEDIUM


async def test_set_level():
    mgr = EffortManager()
    mgr.level = EffortLevel.HIGH
    assert mgr.level == EffortLevel.HIGH


async def test_get_think_budget_default():
    mgr = EffortManager()
    # MEDIUM => multiplier 1.0
    assert mgr.get_think_budget(10_000) == 10_000


async def test_get_think_budget_low():
    mgr = EffortManager(EffortConfig(level=EffortLevel.LOW))
    assert mgr.get_think_budget(10_000) == 2_500


async def test_get_think_budget_max():
    mgr = EffortManager(EffortConfig(level=EffortLevel.MAX))
    assert mgr.get_think_budget(10_000) == 40_000


async def test_get_max_tokens_high():
    mgr = EffortManager(EffortConfig(level=EffortLevel.HIGH))
    assert mgr.get_max_tokens(8192) == int(8192 * 1.5)


async def test_apply_to_kwargs_medium_no_keys():
    """MEDIUM with no think_budget/max_tokens should return unchanged."""
    mgr = EffortManager()
    kwargs = {"temperature": 0.7}
    result = mgr.apply_to_kwargs(kwargs)
    assert "think_budget" not in result
    assert "max_tokens" not in result
    assert result["temperature"] == 0.7


async def test_apply_to_kwargs_medium_with_keys():
    """MEDIUM with existing keys applies 1.0 multiplier (unchanged)."""
    mgr = EffortManager()
    kwargs = {"think_budget": 5000, "max_tokens": 4096}
    result = mgr.apply_to_kwargs(kwargs)
    assert result["think_budget"] == 5000
    assert result["max_tokens"] == 4096


async def test_apply_to_kwargs_high():
    mgr = EffortManager(EffortConfig(level=EffortLevel.HIGH))
    kwargs = {"temperature": 0.5}
    result = mgr.apply_to_kwargs(kwargs)
    # HIGH adds think_budget and max_tokens with multiplier
    assert result["think_budget"] == 20_000
    assert result["max_tokens"] == int(8192 * 1.5)
    assert result["temperature"] == 0.5


async def test_apply_to_kwargs_does_not_mutate():
    mgr = EffortManager(EffortConfig(level=EffortLevel.LOW))
    kwargs = {"max_tokens": 8192}
    result = mgr.apply_to_kwargs(kwargs)
    assert result is not kwargs
    assert kwargs["max_tokens"] == 8192  # original unchanged


async def test_from_env_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("BREADMIND_EFFORT_LEVEL", None)
        mgr = EffortManager.from_env()
        assert mgr.level == EffortLevel.MEDIUM


async def test_from_env_high():
    with patch.dict(os.environ, {"BREADMIND_EFFORT_LEVEL": "high"}):
        mgr = EffortManager.from_env()
        assert mgr.level == EffortLevel.HIGH


async def test_from_string():
    mgr = EffortManager.from_string("max")
    assert mgr.level == EffortLevel.MAX


async def test_from_string_case_insensitive():
    mgr = EffortManager.from_string("LOW")
    assert mgr.level == EffortLevel.LOW


async def test_from_string_unknown_defaults_medium():
    mgr = EffortManager.from_string("turbo")
    assert mgr.level == EffortLevel.MEDIUM


async def test_custom_multipliers():
    config = EffortConfig(
        level=EffortLevel.LOW,
        think_budget_multiplier={
            EffortLevel.LOW: 0.1,
            EffortLevel.MEDIUM: 1.0,
            EffortLevel.HIGH: 3.0,
            EffortLevel.MAX: 5.0,
        },
    )
    mgr = EffortManager(config)
    assert mgr.get_think_budget(10_000) == 1_000
