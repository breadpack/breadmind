"""OpusPlan Strategy — automatic model switching by task phase.

Uses a strong model for planning/architecture and a fast model for
implementation and review, optimising cost and latency while keeping
quality high for critical thinking steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class TaskPhase(str, Enum):
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"



@dataclass
class ModelStrategy:
    planning_model: str = ""      # resolved from tier config if empty
    implementation_model: str = "" # resolved from tier config if empty
    review_model: str = ""        # resolved from tier config if empty
    auto_switch: bool = True


# Keywords used for phase auto-detection
_PLANNING_KEYWORDS = re.compile(
    r"\b(plan|design|architect|approach|strategy|outline|break\s*down|decompose|think)\b",
    re.IGNORECASE,
)
_REVIEW_KEYWORDS = re.compile(
    r"\b(review|verify|check|validate|test|audit|confirm|looks?\s*good)\b",
    re.IGNORECASE,
)
_CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]+?```")


class OpusPlanManager:
    """Auto-switches between strong model (planning) and fast model (implementation).

    - Planning phase: uses strongest model for architecture/design
    - Implementation phase: uses faster model for code generation
    - Review phase: uses fast model for verification
    """

    def __init__(self, strategy: ModelStrategy | None = None) -> None:
        self._strategy = strategy or ModelStrategy()
        self._current_phase = TaskPhase.PLANNING
        self._phase_history: list[tuple[TaskPhase, str]] = []

    # ---- properties -------------------------------------------------------

    @property
    def current_model(self) -> str:
        """Get the model for the current phase."""
        return self._model_for_phase(self._current_phase)

    @property
    def current_phase(self) -> TaskPhase:
        return self._current_phase

    @property
    def phase_history(self) -> list[tuple[TaskPhase, str]]:
        return list(self._phase_history)

    # ---- public API -------------------------------------------------------

    def transition(self, new_phase: TaskPhase) -> str:
        """Transition to a new phase.  Returns the model to use."""
        self._current_phase = new_phase
        model = self._model_for_phase(new_phase)
        self._phase_history.append((new_phase, model))
        return model

    def detect_phase(self, messages: list[dict]) -> TaskPhase:
        """Auto-detect current phase from conversation context.

        Looks for planning keywords, code blocks, and review patterns in the
        most recent messages.
        """
        if not messages:
            return TaskPhase.PLANNING

        # Examine the last few messages (up to 5)
        recent = messages[-5:]
        text = " ".join(m.get("content", "") for m in recent if isinstance(m.get("content"), str))

        # Code blocks are a strong signal for implementation
        code_blocks = _CODE_BLOCK_PATTERN.findall(text)
        has_code = len(code_blocks) > 0

        planning_hits = len(_PLANNING_KEYWORDS.findall(text))
        review_hits = len(_REVIEW_KEYWORDS.findall(text))

        # If we see review keywords and there has been code, it's review
        if review_hits > 0 and has_code:
            return TaskPhase.REVIEW

        # If there is code or few planning keywords, it's implementation
        if has_code and planning_hits == 0:
            return TaskPhase.IMPLEMENTATION

        # If planning keywords dominate, it's planning
        if planning_hits > review_hits:
            return TaskPhase.PLANNING

        # Default: implementation (most common phase)
        return TaskPhase.IMPLEMENTATION

    def get_model_for_turn(self, messages: list[dict]) -> str:
        """Get the appropriate model for the next turn based on auto-detection.

        Returns the model string from ``ModelStrategy``.  When all strategy
        fields are empty the return value is ``""``, which callers should
        treat as "use the default model".
        """
        if not self._strategy.auto_switch:
            return self.current_model

        detected = self.detect_phase(messages)
        return self.transition(detected)

    def get_difficulty_for_turn(self, messages: list[dict]) -> str:
        """Return the difficulty tier for the current turn."""
        _phase_to_difficulty = {
            TaskPhase.PLANNING: "high",
            TaskPhase.IMPLEMENTATION: "medium",
            TaskPhase.REVIEW: "low",
        }
        if not self._strategy.auto_switch:
            return _phase_to_difficulty[self._current_phase]
        detected = self.detect_phase(messages)
        self._current_phase = detected
        return _phase_to_difficulty[detected]

    # ---- internal ---------------------------------------------------------

    def _model_for_phase(self, phase: TaskPhase) -> str:
        mapping = {
            TaskPhase.PLANNING: self._strategy.planning_model,
            TaskPhase.IMPLEMENTATION: self._strategy.implementation_model,
            TaskPhase.REVIEW: self._strategy.review_model,
        }
        return mapping[phase]
