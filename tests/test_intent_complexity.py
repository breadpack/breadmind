"""Tests for Intent complexity detection."""
from breadmind.core.intent import classify, Intent


def test_simple_query_is_simple():
    intent = classify("K8s Pod 목록 보여줘")
    assert intent.complexity == "simple"


def test_multi_domain_is_complex():
    intent = classify("K8s Pod 진단하고 Proxmox 리소스도 확인해줘")
    assert intent.complexity == "complex"


def test_multi_step_is_complex():
    intent = classify("OOMKilled Pod 찾아서 메모리 limit 2배로 올려줘")
    assert intent.complexity == "complex"


def test_single_action_is_simple():
    intent = classify("nginx 재시작해줘")
    assert intent.complexity == "simple"


def test_diagnose_and_fix_is_complex():
    intent = classify("왜 느린지 확인하고 고쳐줘")
    assert intent.complexity == "complex"
