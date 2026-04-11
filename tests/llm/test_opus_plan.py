"""Tests for OpusPlan Strategy (auto model switching)."""

from __future__ import annotations

from breadmind.llm.opus_plan import (
    ModelStrategy, OpusPlanManager, TaskPhase, PHASE_TO_DIFFICULTY,
)


class TestModelStrategy:
    def test_defaults(self):
        s = ModelStrategy()
        # Defaults are empty (resolved from tier config at runtime)
        assert s.planning_model == ""
        assert s.implementation_model == ""
        assert s.review_model == ""
        assert s.auto_switch is True


class TestPhaseTodifficulty:
    def test_mapping(self):
        assert PHASE_TO_DIFFICULTY[TaskPhase.PLANNING] == "high"
        assert PHASE_TO_DIFFICULTY[TaskPhase.IMPLEMENTATION] == "medium"
        assert PHASE_TO_DIFFICULTY[TaskPhase.REVIEW] == "low"


class TestOpusPlanManager:
    def test_initial_phase_is_planning(self):
        mgr = OpusPlanManager()
        assert mgr.current_phase == TaskPhase.PLANNING
        assert mgr.current_model == ""

    def test_transition_changes_phase_and_model(self):
        mgr = OpusPlanManager()
        model = mgr.transition(TaskPhase.IMPLEMENTATION)
        assert mgr.current_phase == TaskPhase.IMPLEMENTATION
        assert model == ""

    def test_transition_records_history(self):
        mgr = OpusPlanManager()
        mgr.transition(TaskPhase.IMPLEMENTATION)
        mgr.transition(TaskPhase.REVIEW)
        history = mgr.phase_history
        assert len(history) == 2
        assert history[0] == (TaskPhase.IMPLEMENTATION, "")
        assert history[1] == (TaskPhase.REVIEW, "")

    def test_detect_phase_empty_messages(self):
        mgr = OpusPlanManager()
        assert mgr.detect_phase([]) == TaskPhase.PLANNING

    def test_detect_phase_planning_keywords(self):
        mgr = OpusPlanManager()
        messages = [{"content": "Let's plan and design the architecture for this feature"}]
        assert mgr.detect_phase(messages) == TaskPhase.PLANNING

    def test_detect_phase_implementation_with_code(self):
        mgr = OpusPlanManager()
        messages = [{"content": "Here is the code:\n```python\nprint('hello')\n```"}]
        assert mgr.detect_phase(messages) == TaskPhase.IMPLEMENTATION

    def test_detect_phase_review_with_code(self):
        mgr = OpusPlanManager()
        messages = [
            {"content": "```python\ndef foo(): pass\n```\nPlease review and verify this code."}
        ]
        assert mgr.detect_phase(messages) == TaskPhase.REVIEW

    def test_get_model_for_turn_auto_switch(self):
        mgr = OpusPlanManager()
        messages = [{"content": "Please plan the approach"}]
        model = mgr.get_model_for_turn(messages)
        assert model == ""
        assert mgr.current_phase == TaskPhase.PLANNING

    def test_get_model_for_turn_auto_switch_disabled(self):
        strategy = ModelStrategy(auto_switch=False)
        mgr = OpusPlanManager(strategy=strategy)
        messages = [{"content": "```python\ncode\n```"}]
        model = mgr.get_model_for_turn(messages)
        # Should return current model without switching
        assert model == ""
        assert mgr.current_phase == TaskPhase.PLANNING

    def test_get_difficulty_for_turn(self):
        mgr = OpusPlanManager()
        messages = [{"content": "Please plan the approach"}]
        difficulty = mgr.get_difficulty_for_turn(messages)
        assert difficulty == "high"
        assert mgr.current_phase == TaskPhase.PLANNING

    def test_get_difficulty_for_turn_implementation(self):
        mgr = OpusPlanManager()
        messages = [{"content": "Here is the code:\n```python\nprint('hello')\n```"}]
        difficulty = mgr.get_difficulty_for_turn(messages)
        assert difficulty == "medium"

    def test_get_difficulty_for_turn_auto_switch_disabled(self):
        strategy = ModelStrategy(auto_switch=False)
        mgr = OpusPlanManager(strategy=strategy)
        messages = [{"content": "```python\ncode\n```"}]
        difficulty = mgr.get_difficulty_for_turn(messages)
        # Should return current phase's difficulty without switching
        assert difficulty == "high"  # initial phase is PLANNING
        assert mgr.current_phase == TaskPhase.PLANNING

    def test_custom_strategy(self):
        strategy = ModelStrategy(
            planning_model="gpt-4",
            implementation_model="gpt-3.5-turbo",
            review_model="gpt-4",
        )
        mgr = OpusPlanManager(strategy=strategy)
        assert mgr.current_model == "gpt-4"
        mgr.transition(TaskPhase.IMPLEMENTATION)
        assert mgr.current_model == "gpt-3.5-turbo"
        mgr.transition(TaskPhase.REVIEW)
        assert mgr.current_model == "gpt-4"

    def test_phase_history_is_copy(self):
        mgr = OpusPlanManager()
        mgr.transition(TaskPhase.IMPLEMENTATION)
        h1 = mgr.phase_history
        h1.append((TaskPhase.REVIEW, "x"))
        assert len(mgr.phase_history) == 1
