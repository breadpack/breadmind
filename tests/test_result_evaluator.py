from breadmind.core.result_evaluator import ResultEvaluator, EvalResult

def test_success_result_is_normal():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=True] Found 3 pods", "List of pods")
    assert result.status == "normal"

def test_failure_result_is_abnormal():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=False] Connection refused", "List of pods")
    assert result.status == "abnormal"
    assert "Connection refused" in result.failure_reason

def test_empty_result_is_abnormal():
    ev = ResultEvaluator()
    result = ev.evaluate("", "Expected some output")
    assert result.status == "abnormal"

def test_timeout_result_is_abnormal():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=False] Tool execution timed out after 60s.", "Pod list")
    assert result.status == "abnormal"
    assert result.is_timeout

def test_normal_result_carries_output():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=True] 3 pods running", "Pod count")
    assert result.output == "[success=True] 3 pods running"
