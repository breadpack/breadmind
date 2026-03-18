"""Tests for urgency scoring in intent classification."""


def test_critical_urgency_korean():
    from breadmind.core.intent import classify
    result = classify("지금 당장 서버 재시작해줘")
    assert result.urgency == "critical"


def test_critical_urgency_english():
    from breadmind.core.intent import classify
    result = classify("ASAP restart the server")
    assert result.urgency == "critical"


def test_high_urgency():
    from breadmind.core.intent import classify
    result = classify("급한 건데 로그 좀 확인해줘")
    assert result.urgency == "high"


def test_low_urgency():
    from breadmind.core.intent import classify
    result = classify("시간 될 때 천천히 확인해줘")
    assert result.urgency == "low"


def test_normal_urgency_default():
    from breadmind.core.intent import classify
    result = classify("서버 상태 확인해줘")
    assert result.urgency == "normal"


def test_urgency_does_not_affect_category():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("지금 당장 할 일 추가해줘")
    assert result.category == IntentCategory.TASK
    assert result.urgency == "critical"
