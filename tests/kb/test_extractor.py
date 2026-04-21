"""Tests for KnowledgeExtractor._chunk helper (Task 4)."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from breadmind.kb.extractor import KnowledgeExtractor, _chunk
from breadmind.kb.types import SourceMeta


def test_chunk_short_text_one_chunk():
    assert _chunk("hello", size=500, overlap=100) == ["hello"]


def test_chunk_exact_size():
    text = "a" * 500
    assert _chunk(text, size=500, overlap=100) == [text]


def test_chunk_long_text_with_overlap():
    text = "a" * 1100
    chunks = _chunk(text, size=500, overlap=100)
    # starts: 0, 400, 800 → 3 chunks of lengths 500, 500, 300
    assert len(chunks) == 3
    assert len(chunks[0]) == 500
    assert len(chunks[1]) == 500
    assert len(chunks[2]) == 300
    # overlap of 100 chars
    assert chunks[0][-100:] == chunks[1][:100]


def test_chunk_empty():
    assert _chunk("", size=500, overlap=100) == []


def test_chunk_rejects_non_positive_size():
    with pytest.raises(ValueError):
        _chunk("x", size=0, overlap=0)


def test_chunk_rejects_overlap_outside_range():
    with pytest.raises(ValueError):
        _chunk("x", size=10, overlap=10)   # overlap == size
    with pytest.raises(ValueError):
        _chunk("x", size=10, overlap=-1)


# ── KnowledgeExtractor.extract tests (Task 5) ─────────────────────────


def _meta(pid=None):
    return SourceMeta(
        source_type="slack_msg",
        source_uri="https://slack.example/x",
        source_ref="ts:1.0",
        original_user="U1",
        project_id=pid or uuid4(),
        extracted_from="slack_thread_resolved",
    )


async def test_extract_returns_candidate(fake_llm_router, fake_sensitive):
    fake_llm_router.script = [json.dumps({
        "candidates": [{
            "proposed_title": "Fix memory leak in payment",
            "proposed_body": "Use weakref for listener set.",
            "proposed_category": "bug_fix",
            "confidence": 0.87,
        }],
    })]
    ex = KnowledgeExtractor(fake_llm_router, fake_sensitive)
    out = await ex.extract("body", _meta())
    assert len(out) == 1
    assert out[0].proposed_category == "bug_fix"
    assert out[0].confidence == 0.87
    assert out[0].sensitive_flag is False
    # Verify the Source dataclass was built with the correct field names
    assert len(out[0].sources) == 1
    assert out[0].sources[0].type == "slack_msg"
    assert out[0].sources[0].uri == "https://slack.example/x"
    assert out[0].sources[0].ref == "ts:1.0"


async def test_extract_filters_low_confidence(fake_llm_router, fake_sensitive):
    fake_llm_router.script = [json.dumps({
        "candidates": [
            {"proposed_title": "a", "proposed_body": "b",
             "proposed_category": "howto", "confidence": 0.59},
            {"proposed_title": "c", "proposed_body": "d",
             "proposed_category": "howto", "confidence": 0.61},
        ],
    })]
    ex = KnowledgeExtractor(fake_llm_router, fake_sensitive)
    out = await ex.extract("body", _meta())
    assert [c.proposed_title for c in out] == ["c"]


async def test_extract_drops_invalid_category(fake_llm_router, fake_sensitive):
    fake_llm_router.script = [json.dumps({
        "candidates": [{
            "proposed_title": "a", "proposed_body": "b",
            "proposed_category": "gossip", "confidence": 0.9,
        }],
    })]
    ex = KnowledgeExtractor(fake_llm_router, fake_sensitive)
    assert await ex.extract("body", _meta()) == []


async def test_extract_flags_sensitive(fake_llm_router, fake_sensitive):
    fake_sensitive.deny_substrings = ["연봉"]
    fake_llm_router.script = [json.dumps({
        "candidates": [{
            "proposed_title": "연봉 협상",
            "proposed_body": "임원 연봉 논의 요약",
            "proposed_category": "decision",
            "confidence": 0.95,
        }],
    })]
    ex = KnowledgeExtractor(fake_llm_router, fake_sensitive)
    out = await ex.extract("body", _meta())
    assert len(out) == 1
    assert out[0].sensitive_flag is True
    assert out[0].proposed_category == "sensitive_blocked"


async def test_extract_long_content_chunked_calls(fake_llm_router, fake_sensitive):
    # 3 chunks of 500/500/300 → seed exactly 3 responses
    fake_llm_router.script = [json.dumps({"candidates": []})] * 3
    ex = KnowledgeExtractor(fake_llm_router, fake_sensitive)
    long_text = "x" * 1100
    await ex.extract(long_text, _meta())
    assert len(fake_llm_router.calls) == 3


async def test_extract_malformed_llm_json_returns_empty(fake_llm_router, fake_sensitive):
    fake_llm_router.script = ["not json at all"]
    ex = KnowledgeExtractor(fake_llm_router, fake_sensitive)
    assert await ex.extract("body", _meta()) == []
