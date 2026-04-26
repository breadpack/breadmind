import uuid
import pytest
from breadmind.memory.event_types import SignalKind
from breadmind.memory.signals import SignalDetector, TurnSnapshot


SID = uuid.uuid4()
OID = uuid.uuid4()


def _snap(**kw) -> TurnSnapshot:
    base = dict(
        user_id="alice",
        session_id=SID,
        org_id=None,
        user_message="",
        last_tool_name=None,
        prior_turn_summary=None,
    )
    base.update(kw)
    return TurnSnapshot(**base)


def test_tool_executed_success():
    d = SignalDetector()
    e = d.on_tool_finished(
        _snap(),
        tool_name="aws_vpc_create",
        tool_args={"region": "ap-northeast-2"},
        ok=True,
        result_text="vpc-123 created",
    )
    assert e is not None and e.kind is SignalKind.TOOL_EXECUTED


def test_tool_failed_marked():
    d = SignalDetector()
    e = d.on_tool_finished(
        _snap(), tool_name="x", tool_args={}, ok=False, result_text="err",
    )
    assert e.kind is SignalKind.TOOL_FAILED


def test_reflexion_fires():
    d = SignalDetector()
    e = d.on_reflexion(_snap(), reflexion_text="learned: increase timeout")
    assert e.kind is SignalKind.REFLEXION


@pytest.mark.parametrize("msg", [
    "아니, 다시 해줘",
    "그게 아니라 다른 region으로 해",
    "no, that's wrong",
    "redo it",
])
def test_user_correction_when_prior_tool_run(msg):
    d = SignalDetector()
    e = d.on_user_message(_snap(user_message=msg, last_tool_name="aws_vpc_create"))
    assert e.kind is SignalKind.USER_CORRECTION


def test_user_correction_requires_prior_tool():
    d = SignalDetector()
    e = d.on_user_message(_snap(user_message="아니, 잘못됐어", last_tool_name=None))
    assert e is None


@pytest.mark.parametrize("msg", [
    "기억해줘: API key는 vault X에 있어",
    "이건 저장해두자",
    "remember this: prod cluster is on us-east-1",
    "Pin this please",
])
def test_explicit_pin(msg):
    d = SignalDetector()
    e = d.on_user_message(_snap(user_message=msg))
    assert e.kind is SignalKind.EXPLICIT_PIN


def test_chitchat_returns_none():
    d = SignalDetector()
    e = d.on_user_message(_snap(user_message="안녕"))
    assert e is None


# ── P3: EN substring "no" must not false-positive on know/nothing/etc ──


@pytest.mark.parametrize("msg", [
    "I don't know what to do",
    "Nothing changed in the output",
    "Travel to the north for a bit",
    "noted, please continue",
    "now show the logs",
    "ignore that for a sec",
])
def test_en_correction_no_false_positive_on_substrings(msg):
    """`no` and other tokens must use word-boundary matching, not substring."""
    d = SignalDetector()
    e = d.on_user_message(_snap(user_message=msg, last_tool_name="aws_vpc_create"))
    assert e is None, f"unexpected USER_CORRECTION on chit-chat: {msg!r}"


@pytest.mark.parametrize("msg", [
    "no, that's wrong",
    "No that didn't work",
    "wrong region; redo",
    "Try again with us-east-1",
    "use ap-northeast-2 instead",
    "incorrect, fix it",
    "not that one",
])
def test_en_correction_word_boundary_still_matches(msg):
    """Whole-word matches must still be detected as USER_CORRECTION."""
    d = SignalDetector()
    e = d.on_user_message(_snap(user_message=msg, last_tool_name="aws_vpc_create"))
    assert e is not None
    assert e.kind is SignalKind.USER_CORRECTION


def test_ko_correction_unaffected_by_en_word_boundary_change():
    """Korean lexicon stays substring-based (Korean has no \\b boundaries)."""
    d = SignalDetector()
    e = d.on_user_message(_snap(
        user_message="아니, 다른 region으로 다시 해줘",
        last_tool_name="aws_vpc_create",
    ))
    assert e is not None
    assert e.kind is SignalKind.USER_CORRECTION


# ── org_id propagation from TurnSnapshot → SignalEvent ──


def test_org_id_propagates_on_tool_finished():
    d = SignalDetector()
    snap = _snap(org_id=OID)
    e = d.on_tool_finished(
        snap,
        tool_name="aws_vpc_create",
        tool_args={"region": "us-east-1"},
        ok=True,
        result_text="vpc-456 created",
    )
    assert e.org_id == OID


def test_org_id_propagates_on_reflexion():
    d = SignalDetector()
    snap = _snap(org_id=OID)
    e = d.on_reflexion(snap, reflexion_text="learned: use smaller timeout")
    assert e.org_id == OID


def test_org_id_propagates_on_user_message_pin():
    d = SignalDetector()
    snap = _snap(org_id=OID, user_message="remember this: staging DB host is db-stg")
    e = d.on_user_message(snap)
    assert e is not None
    assert e.org_id == OID


def test_org_id_propagates_on_user_correction():
    d = SignalDetector()
    snap = _snap(
        org_id=OID,
        user_message="no, that's wrong",
        last_tool_name="aws_vpc_create",
    )
    e = d.on_user_message(snap)
    assert e is not None
    assert e.org_id == OID


def test_org_id_none_when_not_set():
    d = SignalDetector()
    snap = _snap(org_id=None)
    e = d.on_tool_finished(
        snap, tool_name="x", tool_args={}, ok=True, result_text="ok"
    )
    assert e.org_id is None
