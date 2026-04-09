"""Quality-cost optimizer -- maps intent+complexity to minimum quality tier.

Selects cheapest model candidates that meet quality requirements.
"""
from __future__ import annotations

from enum import Enum

from breadmind.core.intent import IntentCategory
from breadmind.llm.pricing import ModelCostRegistry, ModelInfo


class UserPreference(str, Enum):
    """User preference for cost vs quality tradeoff."""
    BUDGET = "budget"       # Prefer cheapest models
    BALANCED = "balanced"   # Default middle ground
    QUALITY = "quality"     # Prefer highest quality


# (IntentCategory, complexity_level) -> minimum quality tier
# complexity_level: "simple" | "moderate" | "complex"
_QUALITY_MATRIX: dict[tuple[IntentCategory, str], int] = {
    # CHAT -- simple conversations
    (IntentCategory.CHAT, "simple"): 1,
    (IntentCategory.CHAT, "moderate"): 1,
    (IntentCategory.CHAT, "complex"): 2,

    # QUERY -- information lookup
    (IntentCategory.QUERY, "simple"): 1,
    (IntentCategory.QUERY, "moderate"): 2,
    (IntentCategory.QUERY, "complex"): 3,

    # EXECUTE -- actions
    (IntentCategory.EXECUTE, "simple"): 2,
    (IntentCategory.EXECUTE, "moderate"): 2,
    (IntentCategory.EXECUTE, "complex"): 3,

    # DIAGNOSE -- troubleshooting (needs high quality)
    (IntentCategory.DIAGNOSE, "simple"): 2,
    (IntentCategory.DIAGNOSE, "moderate"): 3,
    (IntentCategory.DIAGNOSE, "complex"): 4,

    # CONFIGURE -- settings changes
    (IntentCategory.CONFIGURE, "simple"): 1,
    (IntentCategory.CONFIGURE, "moderate"): 2,
    (IntentCategory.CONFIGURE, "complex"): 3,

    # LEARN -- memory ops
    (IntentCategory.LEARN, "simple"): 1,
    (IntentCategory.LEARN, "moderate"): 1,
    (IntentCategory.LEARN, "complex"): 2,

    # SCHEDULE -- calendar
    (IntentCategory.SCHEDULE, "simple"): 1,
    (IntentCategory.SCHEDULE, "moderate"): 2,
    (IntentCategory.SCHEDULE, "complex"): 2,

    # TASK -- todo
    (IntentCategory.TASK, "simple"): 1,
    (IntentCategory.TASK, "moderate"): 2,
    (IntentCategory.TASK, "complex"): 2,

    # SEARCH_FILES
    (IntentCategory.SEARCH_FILES, "simple"): 1,
    (IntentCategory.SEARCH_FILES, "moderate"): 2,
    (IntentCategory.SEARCH_FILES, "complex"): 2,

    # CONTACT
    (IntentCategory.CONTACT, "simple"): 1,
    (IntentCategory.CONTACT, "moderate"): 1,
    (IntentCategory.CONTACT, "complex"): 2,

    # CODING -- development tasks (needs high quality)
    (IntentCategory.CODING, "simple"): 2,
    (IntentCategory.CODING, "moderate"): 3,
    (IntentCategory.CODING, "complex"): 4,
}

# Preference adjustments to the minimum tier
_PREFERENCE_OFFSET: dict[UserPreference, int] = {
    UserPreference.BUDGET: -1,
    UserPreference.BALANCED: 0,
    UserPreference.QUALITY: 1,
}


def get_min_quality_tier(
    category: IntentCategory,
    complexity: str,
    preference: UserPreference = UserPreference.BALANCED,
) -> int:
    """Determine the minimum quality tier for a given intent and complexity.

    Returns tier clamped to [1, 4].
    """
    base = _QUALITY_MATRIX.get((category, complexity), 2)
    adjusted = base + _PREFERENCE_OFFSET.get(preference, 0)
    return max(1, min(4, adjusted))


class QualityCostOptimizer:
    """Selects cheapest model candidates that meet quality requirements."""

    def select_candidates(
        self,
        category: IntentCategory,
        complexity: str,
        urgency: str,
        preference: UserPreference,
        registry: ModelCostRegistry,
        *,
        needs_tools: bool = True,
        needs_thinking: bool = False,
    ) -> list[ModelInfo]:
        """Return model candidates ranked cheapest-first that meet requirements.

        Args:
            category: Classified intent category.
            complexity: "simple", "moderate", or "complex".
            urgency: "low", "normal", "high", or "critical".
            preference: User cost/quality preference.
            registry: Model cost registry to query.
            needs_tools: Whether tool calling is required.
            needs_thinking: Whether extended thinking is required.

        Returns:
            List of ModelInfo sorted cheapest-first.
        """
        min_tier = get_min_quality_tier(category, complexity, preference)

        # Urgent requests bump tier up by 1
        if urgency in ("high", "critical"):
            min_tier = min(4, min_tier + 1)

        candidates = registry.get_cheapest_models(
            min_tier=min_tier,
            supports_tools=True if needs_tools else None,
            supports_thinking=True if needs_thinking else None,
        )

        return candidates
