import uuid
import pytest
from breadmind.memory.event_types import SignalKind
from breadmind.memory.signals import SignalDetector, TurnSnapshot


SID = uuid.uuid4()


def _snap(**kw) -> TurnSnapshot:
    base = dict(
        user_id="alice",
        session_id=SID,
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
