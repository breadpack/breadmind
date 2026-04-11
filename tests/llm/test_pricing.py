"""Tests for ModelCostRegistry -- pricing, capabilities, and YAML loading."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from breadmind.llm.pricing import (
    ModelCostRegistry,
    ModelInfo,
    ModelPricing,
    ModelCapability,
)


def test_fallback_models_loaded():
    """Registry should have hardcoded fallback models without YAML."""
    registry = ModelCostRegistry()
    assert registry.get("claude-haiku-4-5") is not None
    assert registry.get("claude-sonnet-4-6") is not None
    assert registry.get("gemini-2.5-flash") is not None


def test_get_unknown_model_returns_none():
    registry = ModelCostRegistry()
    assert registry.get("nonexistent-model") is None


def test_estimate_cost_basic():
    registry = ModelCostRegistry()
    # claude-haiku-4-5: input=0.80, output=4.0 per million
    cost = registry.estimate_cost("claude-haiku-4-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert abs(cost - 4.80) < 0.01


def test_estimate_cost_zero_for_unknown():
    registry = ModelCostRegistry()
    cost = registry.estimate_cost("unknown-model", input_tokens=1000, output_tokens=1000)
    assert cost == 0.0


def test_estimate_cost_partial_tokens():
    registry = ModelCostRegistry()
    # 500K input, 100K output for claude-sonnet-4-6 (3.0/15.0 per M)
    cost = registry.estimate_cost("claude-sonnet-4-6", input_tokens=500_000, output_tokens=100_000)
    expected = 500_000 * 3.0 / 1_000_000 + 100_000 * 15.0 / 1_000_000
    assert abs(cost - expected) < 0.0001


def test_get_cheapest_models_no_filter():
    registry = ModelCostRegistry()
    models = registry.get_cheapest_models(min_tier=1)
    assert len(models) >= 3
    # Should be sorted cheapest first
    costs = [m.pricing.input + m.pricing.output for m in models]
    assert costs == sorted(costs)


def test_get_cheapest_models_high_tier():
    registry = ModelCostRegistry()
    models = registry.get_cheapest_models(min_tier=3)
    for m in models:
        assert m.capability.quality_tier >= 3


def test_get_cheapest_models_with_tools_filter():
    registry = ModelCostRegistry()
    models = registry.get_cheapest_models(min_tier=1, supports_tools=True)
    for m in models:
        assert m.capability.supports_tools is True


def test_get_cheapest_models_with_thinking_filter():
    registry = ModelCostRegistry()
    models = registry.get_cheapest_models(min_tier=1, supports_thinking=True)
    for m in models:
        assert m.capability.supports_thinking is True


def test_load_from_yaml_valid(tmp_path):
    yaml_content = """
models:
  test-model-1:
    provider: test
    pricing:
      input: 1.0
      output: 2.0
    capability:
      max_context: 100000
      quality_tier: 2
      supports_thinking: false
      supports_tools: true
      supports_streaming: true
      supports_vision: false
"""
    yaml_file = tmp_path / "test_pricing.yaml"
    yaml_file.write_text(yaml_content)

    registry = ModelCostRegistry.load_from_yaml(yaml_file)
    model = registry.get("test-model-1")
    assert model is not None
    assert model.provider == "test"
    assert model.pricing.input == 1.0
    assert model.pricing.output == 2.0
    assert model.capability.quality_tier == 2


def test_load_from_yaml_missing_file():
    registry = ModelCostRegistry.load_from_yaml("/nonexistent/path.yaml")
    # Should still have fallback models
    assert registry.get("claude-haiku-4-5") is not None


def test_load_from_yaml_invalid_format(tmp_path):
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text("just a string, not a dict")

    registry = ModelCostRegistry.load_from_yaml(yaml_file)
    # Fallback models still present
    assert registry.get("claude-sonnet-4-6") is not None


def test_load_from_yaml_merges_with_fallback(tmp_path):
    """YAML models should be added alongside fallback models."""
    yaml_content = """
models:
  custom-model:
    provider: custom
    pricing:
      input: 0.5
      output: 1.0
    capability:
      max_context: 50000
      quality_tier: 1
      supports_tools: true
"""
    yaml_file = tmp_path / "pricing.yaml"
    yaml_file.write_text(yaml_content)

    registry = ModelCostRegistry.load_from_yaml(yaml_file)
    assert registry.get("custom-model") is not None
    # Fallback also present (unless overridden)
    assert registry.get("gemini-2.5-flash") is not None


def test_all_models():
    registry = ModelCostRegistry()
    models = registry.all_models()
    assert len(models) >= 3
    assert all(isinstance(m, ModelInfo) for m in models)


def test_model_pricing_frozen():
    p = ModelPricing(input=1.0, output=2.0)
    with pytest.raises(AttributeError):
        p.input = 5.0  # type: ignore[misc]


def test_model_capability_frozen():
    c = ModelCapability(quality_tier=3)
    with pytest.raises(AttributeError):
        c.quality_tier = 1  # type: ignore[misc]
