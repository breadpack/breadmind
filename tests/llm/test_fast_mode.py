"""Tests for fast mode manager."""
from __future__ import annotations

from breadmind.llm.fast_mode import FastModeManager


async def test_toggle():
    mgr = FastModeManager()
    assert mgr.enabled is False
    result = mgr.toggle()
    assert result is True
    assert mgr.enabled is True
    result = mgr.toggle()
    assert result is False
    assert mgr.enabled is False


async def test_apply_to_kwargs_disabled():
    mgr = FastModeManager()
    kwargs = {"max_tokens": 4096, "temperature": 0.7, "think_budget": 1000}
    result = mgr.apply_to_kwargs(kwargs)
    # When disabled, kwargs should be returned unchanged
    assert result is kwargs


async def test_apply_to_kwargs_enabled():
    mgr = FastModeManager()
    mgr.enable()
    kwargs = {"max_tokens": 4096, "temperature": 0.7}
    result = mgr.apply_to_kwargs(kwargs)
    # Should be a new dict (not the same object)
    assert result is not kwargs


async def test_skip_thinking():
    mgr = FastModeManager()
    mgr.enable()
    kwargs = {"max_tokens": 4096, "think_budget": 1000}
    result = mgr.apply_to_kwargs(kwargs)
    assert "think_budget" not in result


async def test_get_status():
    mgr = FastModeManager()
    status = mgr.get_status()
    assert status["enabled"] is False
    assert status["skip_thinking"] is True
    assert status["prefer_cache"] is True
