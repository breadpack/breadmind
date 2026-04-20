"""Tests for breadmind.kb.sensitive."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from breadmind.kb.sensitive import SensitiveCategory, SensitiveClassifier


@pytest.fixture
def keyword_map() -> dict[SensitiveCategory, list[str]]:
    return {
        SensitiveCategory.HR: ["performance review", "salary", "연봉"],
        SensitiveCategory.LEGAL: ["NDA", "litigation", "M&A"],
        SensitiveCategory.FINANCE: ["payroll", "revenue forecast"],
        SensitiveCategory.SECURITY: ["security incident", "CVE-"],
        SensitiveCategory.PII: ["resident registration number", "주민번호"],
    }


async def test_fast_path_hr_keyword(keyword_map):
    c = SensitiveClassifier(llm_router=AsyncMock(), keyword_map=keyword_map)
    out = await c.classify("Can I see Bob's performance review?")
    assert out is SensitiveCategory.HR


async def test_fast_path_legal_keyword(keyword_map):
    c = SensitiveClassifier(llm_router=AsyncMock(), keyword_map=keyword_map)
    out = await c.classify("ongoing litigation with vendor")
    assert out is SensitiveCategory.LEGAL


async def test_fast_path_security_keyword(keyword_map):
    c = SensitiveClassifier(llm_router=AsyncMock(), keyword_map=keyword_map)
    out = await c.classify("new CVE-2026-1234 in our stack")
    assert out is SensitiveCategory.SECURITY


async def test_fast_path_is_case_insensitive(keyword_map):
    c = SensitiveClassifier(llm_router=AsyncMock(), keyword_map=keyword_map)
    out = await c.classify("please share the PAYROLL spreadsheet")
    assert out is SensitiveCategory.FINANCE


async def test_safe_text_returns_none_without_llm(keyword_map):
    llm = AsyncMock()
    c = SensitiveClassifier(llm_router=llm, keyword_map=keyword_map)
    out = await c.classify("how do I deploy the web service?")
    assert out is None
    llm.generate.assert_not_called()


async def test_slow_path_invoked_for_ambiguous_text(keyword_map):
    llm = AsyncMock()
    llm.generate.return_value = "HR"
    c = SensitiveClassifier(llm_router=llm, keyword_map=keyword_map)
    # 180-char marginal text triggers slow path
    text = (
        "I'm worried about how the team ranks people on the ladder and "
        "whether that affects my bonus next cycle; can you tell me the "
        "criteria used internally?"
    )
    out = await c.classify(text)
    assert out is SensitiveCategory.HR
    llm.generate.assert_awaited_once()


async def test_slow_path_returns_none_when_llm_says_none(keyword_map):
    llm = AsyncMock()
    llm.generate.return_value = "NONE"
    c = SensitiveClassifier(llm_router=llm, keyword_map=keyword_map)
    text = (
        "Thinking through a long philosophical musing about how software "
        "teams collaborate on distributed systems and architecture design "
        "without any specific company facts."
    )
    out = await c.classify(text)
    assert out is None


async def test_slow_path_unknown_label_returns_none(keyword_map):
    llm = AsyncMock()
    llm.generate.return_value = "BANANA"
    c = SensitiveClassifier(llm_router=llm, keyword_map=keyword_map)
    text = (
        "An ambiguous paragraph of moderate length that has no obvious "
        "sensitive keywords but is long enough to hit the slow path "
        "threshold defined in the classifier module."
    )
    out = await c.classify(text)
    assert out is None


async def test_slow_path_tolerates_llm_error(keyword_map):
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("boom")
    c = SensitiveClassifier(llm_router=llm, keyword_map=keyword_map)
    text = (
        "Another moderately long ambiguous paragraph for testing the "
        "fallback behavior of the sensitive classifier when the upstream "
        "LLM provider errors out unexpectedly."
    )
    out = await c.classify(text)
    assert out is None
