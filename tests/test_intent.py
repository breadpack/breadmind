"""Tests for intent classifier."""
import pytest
from breadmind.core.intent import classify, IntentCategory


class TestIntentClassifier:
    def test_diagnose_intent(self):
        intent = classify("서버에서 에러가 발생했어")
        assert intent.category == IntentCategory.DIAGNOSE
        assert intent.confidence > 0

    def test_execute_intent(self):
        intent = classify("nginx 컨테이너를 재시작해줘")
        assert intent.category == IntentCategory.EXECUTE

    def test_query_intent(self):
        intent = classify("현재 디스크 사용량 확인해줘")
        assert intent.category == IntentCategory.QUERY

    def test_configure_intent(self):
        intent = classify("API key를 변경하고 싶어")
        assert intent.category == IntentCategory.CONFIGURE

    def test_learn_intent(self):
        intent = classify("이 서버 IP를 기억해줘: 192.168.1.100")
        assert intent.category == IntentCategory.LEARN

    def test_chat_intent(self):
        intent = classify("안녕")
        assert intent.category == IntentCategory.CHAT

    def test_entity_extraction_ip(self):
        intent = classify("192.168.1.100 서버 상태 확인해줘")
        assert "192.168.1.100" in intent.entities

    def test_entity_extraction_infra(self):
        intent = classify("pod-nginx-abc123 로그 확인")
        assert any("pod-nginx" in e for e in intent.entities)

    def test_tool_hints_for_diagnose(self):
        intent = classify("왜 서버가 죽었어?")
        assert "shell_exec" in intent.tool_hints

    def test_tool_hints_for_learn(self):
        intent = classify("이거 기억해")
        assert "memory_save" in intent.tool_hints

    def test_ambiguous_defaults_to_query(self):
        intent = classify("kubernetes cluster information")
        assert intent.category in (IntentCategory.QUERY, IntentCategory.CHAT)

    def test_mixed_intent_picks_strongest(self):
        # "에러 확인" has both DIAGNOSE (에러) and QUERY (확인)
        intent = classify("에러 로그 확인해줘")
        assert intent.category == IntentCategory.DIAGNOSE

    def test_keywords_extracted(self):
        intent = classify("nginx pod 상태 확인")
        assert "nginx" in intent.keywords
        assert "pod" in intent.keywords
