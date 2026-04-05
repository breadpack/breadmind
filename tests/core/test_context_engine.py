"""Tests for the pluggable context engine."""
from __future__ import annotations

from breadmind.core.context_engine import (
    ContextEngineConfig,
    ContextEngineRegistry,
    ContextPhase,
    ContextState,
    DefaultContextEngine,
    LosslessContextEngine,
)


def test_context_state_usage_ratio():
    state = ContextState(token_count=100_000, max_tokens=200_000)
    assert state.usage_ratio == 0.5


def test_context_state_zero_max_tokens():
    state = ContextState(token_count=100, max_tokens=0)
    assert state.usage_ratio == 0.0


def test_default_engine_bootstrap():
    engine = DefaultContextEngine()
    state = engine.bootstrap("You are a helpful agent.", [{"name": "shell"}])
    assert state.system_prompt == "You are a helpful agent."
    assert len(state.tools) == 1
    assert state.token_count > 0
    assert state.messages == []


def test_default_engine_bootstrap_with_instructions():
    engine = DefaultContextEngine()
    state = engine.bootstrap("System prompt", [], instructions="Extra instructions")
    assert "Extra instructions" in state.system_prompt
    assert "System prompt" in state.system_prompt


def test_default_engine_ingest_and_assemble():
    engine = DefaultContextEngine()
    engine.bootstrap("prompt", [])
    engine.ingest({"role": "user", "content": "Hello"})
    engine.ingest({"role": "assistant", "content": "Hi there"})

    messages = engine.assemble()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_default_engine_compact():
    config = ContextEngineConfig(preserve_recent_turns=2)
    engine = DefaultContextEngine(config=config)
    engine.bootstrap("prompt", [])

    # Add 10 messages (5 turns)
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        engine.ingest({"role": role, "content": f"Message {i}"})

    assert len(engine.state.messages) == 10
    engine.compact()
    # preserve_recent_turns=2 means keep 4 messages (2 user+assistant pairs)
    assert len(engine.state.messages) == 4


def test_default_engine_needs_compaction():
    config = ContextEngineConfig(max_tokens=100, compact_threshold=0.75)
    engine = DefaultContextEngine(config=config)
    engine._state.token_count = 74
    assert engine.needs_compaction() is False
    engine._state.token_count = 76
    assert engine.needs_compaction() is True


def test_default_engine_after_turn():
    engine = DefaultContextEngine()
    engine.bootstrap("prompt", [])
    # Should not raise
    engine.after_turn({"role": "assistant", "content": "done"})


def test_lossless_engine_compact_creates_summary():
    config = ContextEngineConfig(preserve_recent_turns=1)
    engine = LosslessContextEngine(config=config)
    engine.bootstrap("prompt", [])

    engine.ingest({"role": "user", "content": "First question"})
    engine.ingest({"role": "assistant", "content": "First answer"})
    engine.ingest({"role": "user", "content": "Second question"})
    engine.ingest({"role": "assistant", "content": "Second answer"})

    engine.compact()

    # Recent messages preserved
    assert len(engine.state.messages) == 2
    # Summary was created
    assert len(engine._summaries) == 1

    # Assemble should include summary context
    assembled = engine.assemble()
    assert len(assembled) == 4  # summary pair + 2 recent messages
    assert "[Previous context summary]" in assembled[0]["content"]


def test_lossless_engine_custom_summarizer():
    config = ContextEngineConfig(preserve_recent_turns=1)
    custom_called = []

    def my_summarizer(messages):
        custom_called.append(len(messages))
        return "Custom summary of conversation"

    engine = LosslessContextEngine(config=config, summarizer=my_summarizer)
    engine.bootstrap("prompt", [])
    engine.ingest({"role": "user", "content": "Q1"})
    engine.ingest({"role": "assistant", "content": "A1"})
    engine.ingest({"role": "user", "content": "Q2"})
    engine.ingest({"role": "assistant", "content": "A2"})

    engine.compact()
    assert len(custom_called) == 1
    assert custom_called[0] == 2  # 2 old messages summarized
    assert "Custom summary" in engine._summaries[0]


def test_prepare_subagent():
    engine = DefaultContextEngine()
    engine.bootstrap("System prompt", [{"name": "tool1"}])
    engine.ingest({"role": "user", "content": "Main task"})

    sub_state = engine.prepare_subagent("Do subtask X")
    assert sub_state.system_prompt == "System prompt"
    assert len(sub_state.tools) == 1
    assert len(sub_state.messages) == 1
    assert sub_state.messages[0]["content"] == "Do subtask X"
    assert sub_state.metadata["parent_task"] == "Do subtask X"


def test_on_subagent_ended():
    engine = DefaultContextEngine()
    engine.bootstrap("prompt", [])
    engine.ingest({"role": "user", "content": "Do something"})

    engine.on_subagent_ended({"summary": "Subtask completed successfully"})
    assert len(engine.state.messages) == 2
    assert "[subagent result]" in engine.state.messages[-1]["content"]


def test_registry_create_default():
    engine = ContextEngineRegistry.create("default")
    assert isinstance(engine, DefaultContextEngine)


def test_registry_create_lossless():
    engine = ContextEngineRegistry.create("lossless")
    assert isinstance(engine, LosslessContextEngine)


def test_registry_unknown_raises():
    try:
        ContextEngineRegistry.create("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError as e:
        assert "nonexistent" in str(e)


def test_registry_list_engines():
    engines = ContextEngineRegistry.list_engines()
    assert "default" in engines
    assert "lossless" in engines


def test_context_phase_values():
    """Verify all 7 lifecycle phases exist."""
    assert len(ContextPhase) == 7
    assert ContextPhase.BOOTSTRAP.value == "bootstrap"
    assert ContextPhase.PREPARE_SUBAGENT.value == "prepare_subagent"
    assert ContextPhase.ON_SUBAGENT_ENDED.value == "on_subagent_ended"
