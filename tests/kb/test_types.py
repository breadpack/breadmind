"""P1/P2/P3 dataclass tests."""
from __future__ import annotations

from uuid import uuid4

from breadmind.kb.types import (
    Confidence,
    EnforcedAnswer,
    ExtractedCandidate,
    InsufficientEvidence,
    KBHit,
    PromotionCandidate,
    Source,
    SourceMeta,
)


def test_source_is_frozen():
    s = Source(type="confluence", uri="https://wiki/x", ref="v1")
    assert s.type == "confluence"
    try:
        s.type = "notion"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Source must be frozen")


def test_kb_hit_defaults_empty_sources():
    hit = KBHit(knowledge_id=1, title="t", body="b", score=0.5)
    assert hit.sources == []


def test_enforced_answer_carries_citations():
    src = Source(type="slack_msg", uri="https://slack/p1", ref=None)
    ans = EnforcedAnswer(text="because X", citations=[src])
    assert ans.citations[0].uri == "https://slack/p1"


def test_confidence_values():
    assert Confidence.HIGH.value == "high"
    assert Confidence.MEDIUM.value == "medium"
    assert Confidence.LOW.value == "low"


def test_insufficient_evidence_is_exception():
    assert issubclass(InsufficientEvidence, Exception)


# ── P3 dataclass tests ──────────────────────────────────────────────────


def test_source_meta_slots():
    m = SourceMeta(
        source_type="slack_msg",
        source_uri="https://slack.com/x",
        source_ref="ts:1.0",
        original_user="U1",
        project_id=uuid4(),
        extracted_from="slack_thread_resolved",
    )
    assert m.source_type == "slack_msg"


def test_extracted_candidate_defaults_sensitive_false():
    c = ExtractedCandidate(
        proposed_title="t",
        proposed_body="b",
        proposed_category="howto",
        confidence=0.9,
        sources=[],
        original_user=None,
        project_id=uuid4(),
    )
    assert c.sensitive_flag is False


def test_promotion_candidate_minimal():
    p = PromotionCandidate(
        id=1,
        project_id=uuid4(),
        extracted_from="x",
        original_user=None,
        proposed_title="t",
        proposed_body="b",
        proposed_category="howto",
        sources_json=[],
        confidence=0.8,
        status="pending",
    )
    assert p.status == "pending"
    assert p.sensitive_flag is False


def test_public_import_from_kb_package():
    """Ensure the three new types are re-exported from breadmind.kb."""
    from breadmind.kb import (  # noqa: F401
        ExtractedCandidate,
        PromotionCandidate,
        SourceMeta,
    )
