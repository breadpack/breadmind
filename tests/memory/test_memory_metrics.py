"""T13 — Prometheus metric registration for episodic memory pipeline.

The plan-spec test asserts that the five canonical metric names are present
on the prometheus_client default REGISTRY after the memory metrics module is
imported. Wiring tests below cover the call-site increments at signal,
recorder, and store boundaries.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from prometheus_client import REGISTRY


# Import once so registration occurs before REGISTRY.collect() is called.
import breadmind.memory.metrics as mm  # noqa: E402,F401  (side-effect: registers)


def test_memory_metric_names_registered() -> None:
    # prometheus_client strips the trailing ``_total`` from Counter family
    # names. Histogram families keep their full name. The exposition output
    # restores ``_total`` on the Counter sample lines.
    names = {m.name for m in REGISTRY.collect()}
    assert "breadmind_memory_signal_detected" in names
    assert "breadmind_memory_normalize" in names
    assert "breadmind_memory_normalize_latency_seconds" in names
    assert "breadmind_memory_recall" in names
    assert "breadmind_memory_recall_hit_count" in names


# ── Wiring tests ──────────────────────────────────────────────────────


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def test_signal_detector_increments_counter_on_pin() -> None:
    from breadmind.memory.signals import SignalDetector, TurnSnapshot

    before = _counter_value(mm.memory_signal_detected_total, kind="explicit_pin")
    detector = SignalDetector()
    snap = TurnSnapshot(
        user_id="u",
        session_id=None,
        user_message="이건 기억해줘",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    evt = detector.on_user_message(snap)
    assert evt is not None
    after = _counter_value(mm.memory_signal_detected_total, kind="explicit_pin")
    assert after == before + 1.0


def test_signal_detector_increments_counter_on_tool_finished() -> None:
    from breadmind.memory.signals import SignalDetector, TurnSnapshot

    before_ok = _counter_value(
        mm.memory_signal_detected_total, kind="tool_executed",
    )
    before_fail = _counter_value(
        mm.memory_signal_detected_total, kind="tool_failed",
    )
    detector = SignalDetector()
    snap = TurnSnapshot(
        user_id="u",
        session_id=None,
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    detector.on_tool_finished(
        snap,
        tool_name="echo",
        tool_args={"x": 1},
        ok=True,
        result_text="ok",
    )
    detector.on_tool_finished(
        snap,
        tool_name="echo",
        tool_args={"x": 1},
        ok=False,
        result_text="boom",
    )
    after_ok = _counter_value(
        mm.memory_signal_detected_total, kind="tool_executed",
    )
    after_fail = _counter_value(
        mm.memory_signal_detected_total, kind="tool_failed",
    )
    assert after_ok == before_ok + 1.0
    assert after_fail == before_fail + 1.0


def test_normalize_records_latency_and_outcome_recorded() -> None:
    from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
    from breadmind.memory.event_types import SignalEvent, SignalKind

    store = AsyncMock()
    store.write = AsyncMock(return_value=1)
    llm = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value={
            "should_record": True,
            "summary": "s",
            "outcome": "success",
            "keywords": ["k"],
        },
    )
    recorder = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig())

    evt = SignalEvent(
        kind=SignalKind.TOOL_EXECUTED,
        user_id="u",
        session_id=None,
        user_message=None,
        tool_name="echo",
        tool_args={"x": 1},
        tool_result_text="ok",
        prior_turn_summary=None,
    )

    before = _counter_value(mm.memory_normalize_total, outcome="recorded")
    asyncio.run(recorder.record(evt))
    after = _counter_value(mm.memory_normalize_total, outcome="recorded")
    assert after == before + 1.0
    # Histogram observed at least once.
    hist_count = sum(b.get() for b in mm.memory_normalize_latency_seconds._buckets)
    assert hist_count >= 1


def test_normalize_outcome_skipped_by_llm() -> None:
    from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
    from breadmind.memory.event_types import SignalEvent, SignalKind

    store = AsyncMock()
    store.write = AsyncMock(return_value=1)
    llm = AsyncMock()
    llm.complete_json = AsyncMock(return_value={"should_record": False})
    recorder = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig())

    evt = SignalEvent(
        kind=SignalKind.TOOL_EXECUTED,
        user_id="u",
        session_id=None,
        user_message=None,
        tool_name="echo",
        tool_args={"x": 1},
        tool_result_text="ok",
        prior_turn_summary=None,
    )

    before = _counter_value(mm.memory_normalize_total, outcome="skipped_by_llm")
    asyncio.run(recorder.record(evt))
    after = _counter_value(mm.memory_normalize_total, outcome="skipped_by_llm")
    assert after == before + 1.0


def test_normalize_outcome_raw_fallback_when_llm_raises() -> None:
    from breadmind.memory.episodic_recorder import EpisodicRecorder, RecorderConfig
    from breadmind.memory.event_types import SignalEvent, SignalKind

    store = AsyncMock()
    store.write = AsyncMock(return_value=1)
    llm = AsyncMock()
    llm.complete_json = AsyncMock(side_effect=RuntimeError("llm down"))
    recorder = EpisodicRecorder(store=store, llm=llm, config=RecorderConfig())

    evt = SignalEvent(
        kind=SignalKind.TOOL_EXECUTED,
        user_id="u",
        session_id=None,
        user_message=None,
        tool_name="echo",
        tool_args={"x": 1},
        tool_result_text="ok",
        prior_turn_summary=None,
    )

    before_raw = _counter_value(mm.memory_normalize_total, outcome="raw_fallback")
    before_failed = _counter_value(mm.memory_normalize_total, outcome="llm_failed")
    asyncio.run(recorder.record(evt))
    after_raw = _counter_value(mm.memory_normalize_total, outcome="raw_fallback")
    after_failed = _counter_value(mm.memory_normalize_total, outcome="llm_failed")
    assert after_raw == before_raw + 1.0
    assert after_failed == before_failed + 1.0


def test_recall_metric_incremented_at_turn_caller() -> None:
    """ContextBuilder.build_recalled_episodes uses trigger='turn'."""
    from breadmind.memory.context_builder import ContextBuilder
    from breadmind.memory.working import WorkingMemory

    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    cb = ContextBuilder(working_memory=WorkingMemory(), episodic_store=store)

    before = _counter_value(mm.memory_recall_total, trigger="turn")
    asyncio.run(cb.build_recalled_episodes(user_id="u", message="hi"))
    after = _counter_value(mm.memory_recall_total, trigger="turn")
    assert after == before + 1.0
    # Histogram observed (with 0 hits since search returned []).
    total = sum(b.get() for b in mm.memory_recall_hit_count._buckets)
    assert total >= 1


def test_recall_metric_incremented_at_tool_caller() -> None:
    """ToolExecutor._do_recall uses trigger='tool'."""
    from breadmind.core.safety import SafetyGuard
    from breadmind.core.tool_executor import ToolExecutor
    from breadmind.tools.registry import ToolRegistry

    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    executor = ToolExecutor(
        tool_registry=ToolRegistry(),
        safety_guard=SafetyGuard(),
        episodic_store=store,
    )

    before = _counter_value(mm.memory_recall_total, trigger="tool")
    asyncio.run(executor._do_recall(tool_name="echo", args={}, user_id="u"))
    after = _counter_value(mm.memory_recall_total, trigger="tool")
    assert after == before + 1.0
