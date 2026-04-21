"""Tests for KnowledgeExtractor._chunk helper (Task 4)."""
from __future__ import annotations

import pytest

from breadmind.kb.extractor import _chunk


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
