from breadmind.kb.types import (
    Confidence,
    EnforcedAnswer,
    InsufficientEvidence,
    KBHit,
    Source,
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
