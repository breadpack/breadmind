"""Tests for domain entity preservation in summarization."""


def test_extract_task_ids():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    messages = [
        {"content": "할 일 생성 완료: 'Buy milk' [ID: abc12345]"},
        {"content": "할 일 업데이트 완료 [ID: def67890]"},
    ]
    refs = summarizer.extract_domain_references(messages)
    assert "abc12345" in refs["tasks"]
    assert "def67890" in refs["tasks"]


def test_extract_event_mentions():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    messages = [
        {"content": "📅 10분 후: Team Standup"},
        {"content": "일정: Sprint Planning (14:00~15:00)"},
    ]
    refs = summarizer.extract_domain_references(messages)
    assert any("Standup" in e for e in refs["events"])


def test_extract_contact_mentions():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    messages = [
        {"content": "📇 연락처 검색 결과:\n  • Alice Smith | 📧 alice@example.com"},
    ]
    refs = summarizer.extract_domain_references(messages)
    assert len(refs["contacts"]) >= 1


def test_extract_deadlines():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    messages = [
        {"content": "⚠️ 마감 임박: Submit report (6시간 남음)"},
        {"content": "Task due: 2026-03-18T18:00"},
    ]
    refs = summarizer.extract_domain_references(messages)
    assert len(refs["deadlines"]) >= 1


def test_format_domain_context():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    refs = {"tasks": ["abc123"], "events": ["Standup"], "contacts": [], "deadlines": ["03/18 18:00"]}
    result = summarizer.format_domain_context(refs)
    assert "Domain Context" in result
    assert "abc123" in result
    assert "Standup" in result


def test_format_domain_context_empty():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    refs = {"tasks": [], "events": [], "contacts": [], "deadlines": []}
    result = summarizer.format_domain_context(refs)
    assert result == ""


def test_deduplicates_references():
    from breadmind.memory.summarizer import ConversationSummarizer
    summarizer = ConversationSummarizer()
    messages = [
        {"content": "할 일 [ID: abc12345] 확인"},
        {"content": "할 일 [ID: abc12345] 업데이트"},
    ]
    refs = summarizer.extract_domain_references(messages)
    assert refs["tasks"].count("abc12345") == 1
