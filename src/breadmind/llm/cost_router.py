"""Cost router -- central orchestrator for cost-optimized model selection.

Combines pricing registry, quality optimizer, budget manager, and success
tracker to select the cheapest model that meets quality requirements.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from breadmind.core.intent import IntentCategory
from breadmind.llm.budget import BudgetManager
from breadmind.llm.optimizer import QualityCostOptimizer, UserPreference
from breadmind.llm.pricing import ModelCostRegistry
from breadmind.llm.quality_feedback import SuccessTracker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Minimum success rate to consider a model viable
_MIN_SUCCESS_RATE = 0.3


class CostRouter:
    """Selects the optimal (provider, model) pair for a given request.

    Algorithm:
    1. Determine minimum quality tier from intent + complexity + preference
    2. Get cheapest candidate models meeting tier requirements
    3. Filter by budget constraints
    4. Filter by success rate (drop models with poor track record)
    5. Filter by available providers
    6. Return cheapest remaining candidate, or fallback to default
    """

    def __init__(
        self,
        registry: ModelCostRegistry,
        optimizer: QualityCostOptimizer,
        budget: BudgetManager,
        success_tracker: SuccessTracker,
        available_providers: set[str] | None = None,
        default_provider: str = "anthropic",
        default_model: str = "claude-sonnet-4-6",
    ) -> None:
        self._registry = registry
        self._optimizer = optimizer
        self._budget = budget
        self._success_tracker = success_tracker
        self._available_providers = available_providers or {"anthropic"}
        self._default_provider = default_provider
        self._default_model = default_model
        self.enabled: bool = False  # Disabled by default for gradual rollout

    def select_model(
        self,
        category: IntentCategory,
        complexity: str,
        urgency: str,
        estimated_tokens: int = 1000,
        preference: UserPreference = UserPreference.BALANCED,
        *,
        needs_tools: bool = True,
        needs_thinking: bool = False,
    ) -> tuple[str, str]:
        """Select the best (provider, model) pair for the request.

        Returns:
            Tuple of (provider_name, model_id).
        """
        if not self.enabled:
            return self._default_provider, self._default_model

        # Step 1-2: Get candidates from optimizer
        candidates = self._optimizer.select_candidates(
            category=category,
            complexity=complexity,
            urgency=urgency,
            preference=preference,
            registry=self._registry,
            needs_tools=needs_tools,
            needs_thinking=needs_thinking,
        )

        if not candidates:
            logger.debug("No candidates from optimizer, using default")
            return self._default_provider, self._default_model

        intent_value = category.value

        for model_info in candidates:
            # Step 3: Filter by available providers
            if model_info.provider not in self._available_providers:
                continue

            # Step 4: Filter by budget
            estimated_cost = self._registry.estimate_cost(
                model_info.model_id,
                input_tokens=estimated_tokens,
                output_tokens=estimated_tokens,
            )
            if not self._budget.can_afford(model_info.provider, estimated_cost):
                logger.debug(
                    "Model %s filtered by budget (est. $%.6f)",
                    model_info.model_id, estimated_cost,
                )
                continue

            # Step 5: Filter by success rate
            success_rate = self._success_tracker.get_success_rate(
                model_info.model_id, intent_value,
            )
            if success_rate < _MIN_SUCCESS_RATE:
                logger.debug(
                    "Model %s filtered by success rate (%.2f < %.2f)",
                    model_info.model_id, success_rate, _MIN_SUCCESS_RATE,
                )
                continue

            # Step 6: First surviving candidate is the cheapest viable one
            logger.info(
                "CostRouter selected %s/%s for %s/%s (est. $%.6f)",
                model_info.provider, model_info.model_id,
                category.value, complexity, estimated_cost,
            )
            return model_info.provider, model_info.model_id

        # No viable candidate found -- fallback
        logger.info("CostRouter: no viable candidate, using default %s/%s",
                     self._default_provider, self._default_model)
        return self._default_provider, self._default_model

    def record_result(
        self,
        provider: str,
        model: str,
        intent: str,
        success: bool,
        cost: float,
        latency_ms: float,
    ) -> None:
        """Record the result of an LLM call for future optimization."""
        self._budget.record_cost(provider, model, cost)
        self._success_tracker.record(model, intent, success, cost, latency_ms)

        # Check alerts
        alerts = self._budget.check_alerts()
        for alert in alerts:
            logger.warning("Budget alert: %s", alert)

    @property
    def registry(self) -> ModelCostRegistry:
        return self._registry

    @property
    def budget(self) -> BudgetManager:
        return self._budget
