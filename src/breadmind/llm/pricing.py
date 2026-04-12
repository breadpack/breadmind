"""Model cost registry -- consolidates pricing and capability metadata.

Loads from config/model_pricing.yaml with hardcoded fallback for core models.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """Cost per 1 million tokens (USD)."""
    input: float = 0.0
    output: float = 0.0
    cache_creation: float = 0.0
    cache_read: float = 0.0


@dataclass(frozen=True)
class ModelCapability:
    """Model capability metadata."""
    max_context: int = 200_000
    quality_tier: int = 2  # 1=low, 2=medium, 3=high, 4=premium
    supports_thinking: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False


@dataclass(frozen=True)
class ModelInfo:
    """Full model descriptor: identity + pricing + capability."""
    model_id: str
    provider: str
    pricing: ModelPricing = field(default_factory=ModelPricing)
    capability: ModelCapability = field(default_factory=ModelCapability)


# Hardcoded fallback for when YAML is missing or incomplete
_FALLBACK_MODELS: dict[str, ModelInfo] = {
    "claude-haiku-4-5": ModelInfo(
        model_id="claude-haiku-4-5",
        provider="anthropic",
        pricing=ModelPricing(input=0.80, output=4.0, cache_creation=1.0, cache_read=0.08),
        capability=ModelCapability(max_context=200_000, quality_tier=2, supports_thinking=True, supports_tools=True, supports_vision=True),
    ),
    "claude-sonnet-4-6": ModelInfo(
        model_id="claude-sonnet-4-6",
        provider="anthropic",
        pricing=ModelPricing(input=3.0, output=15.0, cache_creation=3.75, cache_read=0.30),
        capability=ModelCapability(max_context=200_000, quality_tier=3, supports_thinking=True, supports_tools=True, supports_vision=True),
    ),
    "gemini-2.5-flash": ModelInfo(
        model_id="gemini-2.5-flash",
        provider="google",
        pricing=ModelPricing(input=0.15, output=0.60),
        capability=ModelCapability(max_context=1_000_000, quality_tier=1, supports_thinking=True, supports_tools=True, supports_vision=True),
    ),
}


class ModelCostRegistry:
    """Central registry for model pricing and capabilities."""

    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = dict(_FALLBACK_MODELS)

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> ModelCostRegistry:
        """Load model definitions from a YAML file.

        Falls back to hardcoded defaults if the file is missing or malformed.
        """
        registry = cls()
        yaml_path = Path(path)
        if not yaml_path.exists():
            logger.warning("Model pricing YAML not found at %s, using fallback", path)
            return registry

        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            logger.exception("Failed to parse model pricing YAML, using fallback")
            return registry

        if not isinstance(data, dict) or "models" not in data:
            logger.warning("Invalid model pricing YAML format, using fallback")
            return registry

        for model_id, info in data["models"].items():
            try:
                pricing_data = info.get("pricing", {})
                cap_data = info.get("capability", {})
                model_info = ModelInfo(
                    model_id=model_id,
                    provider=info.get("provider", "unknown"),
                    pricing=ModelPricing(
                        input=pricing_data.get("input", 0.0),
                        output=pricing_data.get("output", 0.0),
                        cache_creation=pricing_data.get("cache_creation", 0.0),
                        cache_read=pricing_data.get("cache_read", 0.0),
                    ),
                    capability=ModelCapability(
                        max_context=cap_data.get("max_context", 200_000),
                        quality_tier=cap_data.get("quality_tier", 2),
                        supports_thinking=cap_data.get("supports_thinking", False),
                        supports_tools=cap_data.get("supports_tools", True),
                        supports_streaming=cap_data.get("supports_streaming", True),
                        supports_vision=cap_data.get("supports_vision", False),
                    ),
                )
                registry._models[model_id] = model_info
            except Exception:
                logger.warning("Skipping invalid model entry: %s", model_id)

        return registry

    def get(self, model_id: str) -> ModelInfo | None:
        """Look up a model by ID."""
        return self._models.get(model_id)

    def all_models(self) -> list[ModelInfo]:
        """Return all registered models."""
        return list(self._models.values())

    def estimate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost in USD for a given token count.

        Returns 0.0 if the model is unknown.
        """
        info = self._models.get(model_id)
        if info is None:
            return 0.0
        per_million = 1_000_000.0
        return (
            input_tokens * info.pricing.input / per_million
            + output_tokens * info.pricing.output / per_million
        )

    def get_cheapest_models(
        self,
        min_tier: int = 1,
        supports_tools: bool | None = None,
        supports_thinking: bool | None = None,
    ) -> list[ModelInfo]:
        """Return models meeting minimum requirements, sorted cheapest first.

        Cost is approximated as (input + output) pricing sum for ranking.
        """
        candidates: list[ModelInfo] = []
        for m in self._models.values():
            if m.capability.quality_tier < min_tier:
                continue
            if supports_tools is not None and m.capability.supports_tools != supports_tools:
                continue
            if supports_thinking is not None and m.capability.supports_thinking != supports_thinking:
                continue
            candidates.append(m)

        candidates.sort(key=lambda m: m.pricing.input + m.pricing.output)
        return candidates
