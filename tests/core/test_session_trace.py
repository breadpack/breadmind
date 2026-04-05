"""Tests for session trace auditing."""

import time

import pytest

from breadmind.core.session_trace import SessionTrace, SessionTracer, TraceEntry


def test_tracer_creates_unique_trace_id():
    t1 = SessionTracer(session_id="s1")
    t2 = SessionTracer(session_id="s1")
    assert t1.trace_id != t2.trace_id


def test_record_adds_entry():
    tracer = SessionTracer(session_id="sess1")
    entry = tracer.record("agent-1", "tool_call", {"tool": "shell"})
    assert isinstance(entry, TraceEntry)
    assert entry.agent_id == "agent-1"
    assert entry.action == "tool_call"
    assert entry.details == {"tool": "shell"}
    assert len(tracer.trace.entries) == 1


def test_record_timestamps_increase():
    tracer = SessionTracer()
    e1 = tracer.record("a", "llm_request")
    e2 = tracer.record("a", "decision")
    assert e2.timestamp >= e1.timestamp


def test_signature_deterministic():
    tracer = SessionTracer()
    tracer.record("agent-1", "tool_call")
    sig1 = tracer.trace.signature
    sig2 = tracer.trace.signature
    assert sig1 == sig2
    assert len(sig1) == 16


def test_signature_changes_with_entries():
    tracer = SessionTracer()
    tracer.record("agent-1", "tool_call")
    sig1 = tracer.trace.signature
    tracer.record("agent-1", "decision")
    sig2 = tracer.trace.signature
    assert sig1 != sig2


def test_spawn_child_creates_linked_tracer():
    parent = SessionTracer(session_id="main")
    child = parent.spawn_child("sub-agent-1")
    assert isinstance(child, SessionTracer)
    assert child.trace_id != parent.trace_id
    assert child.trace.session_id == "main"
    # Parent should have a subagent_spawn entry
    spawn_entries = [
        e for e in parent.trace.entries if e.action == "subagent_spawn"
    ]
    assert len(spawn_entries) == 1
    assert spawn_entries[0].details["child_trace_id"] == child.trace_id


def test_get_chain_includes_children():
    parent = SessionTracer(session_id="s")
    child = parent.spawn_child("child-1")
    child.record("child-1", "tool_call")
    chain = parent.get_chain()
    assert len(chain) == 2
    assert chain[0].trace_id == parent.trace_id
    assert chain[1].trace_id == child.trace_id


def test_get_chain_nested_children():
    root = SessionTracer()
    child = root.spawn_child("c1")
    grandchild = child.spawn_child("c2")
    grandchild.record("c2", "decision")
    chain = root.get_chain()
    assert len(chain) == 3


def test_export_and_from_dict_roundtrip():
    tracer = SessionTracer(session_id="round-trip")
    tracer.record("agent-1", "llm_request", {"model": "claude"})
    tracer.record("agent-1", "tool_call", {"tool": "shell"})
    child = tracer.spawn_child("sub-1")
    child.record("sub-1", "decision", {"choice": "approve"})

    exported = tracer.export()
    restored = SessionTracer.from_dict(exported)

    assert restored.trace_id == tracer.trace_id
    assert restored.trace.session_id == "round-trip"
    # 2 manual records + 1 subagent_spawn = 3 entries
    assert len(restored.trace.entries) == 3
    assert restored.trace.signature == tracer.trace.signature


def test_verify_integrity_valid():
    tracer = SessionTracer()
    tracer.record("a", "tool_call")
    tracer.record("a", "decision")
    assert tracer.verify_integrity() is True


def test_verify_integrity_detects_tamper():
    tracer = SessionTracer()
    tracer.record("a", "tool_call")
    tracer.record("a", "decision")
    # Tamper with an entry
    tracer.trace.entries[0].action = "TAMPERED"
    assert tracer.verify_integrity() is False


def test_verify_integrity_empty_trace():
    tracer = SessionTracer()
    assert tracer.verify_integrity() is True


def test_export_structure():
    tracer = SessionTracer(session_id="export-test")
    tracer.record("a", "llm_request")
    data = tracer.export()
    assert "trace_id" in data
    assert "session_id" in data
    assert "entries" in data
    assert "children" in data
    assert "signature" in data
    assert data["session_id"] == "export-test"
    assert len(data["entries"]) == 1


def test_empty_trace_signature():
    trace = SessionTrace()
    sig = trace.signature
    # Empty entries should still produce a valid hash
    assert isinstance(sig, str)
    assert len(sig) == 16
