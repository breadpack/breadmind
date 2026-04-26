import uuid

from breadmind.memory.event_types import (
    SignalKind, SignalEvent, stable_hash, keyword_extract,
)


def test_stable_hash_is_8_chars_and_deterministic():
    a = stable_hash({"region": "ap-northeast-2", "name": "vpc-a"})
    b = stable_hash({"name": "vpc-a", "region": "ap-northeast-2"})  # same dict, different order
    assert a == b
    assert len(a) == 8
    assert all(c in "0123456789abcdef" for c in a)


def test_stable_hash_none_or_empty():
    assert stable_hash(None) is None
    assert stable_hash({}) is None


def test_keyword_extract_korean_english_dedup_stopwords_limit():
    words = keyword_extract(
        "VPC를 ap-northeast-2 region에 만들어줘 and connect to subnet"
    )
    assert "vpc" in words
    assert "subnet" in words
    assert "ap-northeast-2" in words
    assert "the" not in words and "에" not in words
    assert len(words) <= 12
    # dedupe
    again = keyword_extract("vpc vpc vpc")
    assert again.count("vpc") == 1


def test_signal_event_minimal_fields():
    e = SignalEvent(
        kind=SignalKind.TOOL_EXECUTED,
        user_id="alice",
        session_id=None,
        user_message=None,
        tool_name="aws_vpc_create",
        tool_args={"region": "ap-northeast-2"},
        tool_result_text="ok",
        prior_turn_summary=None,
    )
    assert e.kind is SignalKind.TOOL_EXECUTED
    assert e.tool_args["region"] == "ap-northeast-2"


def test_signal_event_org_id_frozen_roundtrip():
    oid = uuid.uuid4()
    e = SignalEvent(
        kind=SignalKind.REFLEXION,
        user_id="bob",
        session_id=None,
        org_id=oid,
        user_message="learned something",
        tool_name=None,
        tool_args=None,
        tool_result_text=None,
        prior_turn_summary=None,
    )
    assert e.org_id == oid
