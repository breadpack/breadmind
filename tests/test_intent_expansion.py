"""Tests for expanded intent categories."""


def test_schedule_intent_korean():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("내일 3시에 회의 잡아줘")
    assert result.category == IntentCategory.SCHEDULE
    assert "event_create" in result.tool_hints


def test_schedule_intent_english():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("Schedule a meeting for tomorrow at 3pm")
    assert result.category == IntentCategory.SCHEDULE


def test_task_intent():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("할 일 목록 보여줘")
    assert result.category == IntentCategory.TASK
    assert "task_list" in result.tool_hints


def test_task_create_intent():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("우유 사기를 할 일에 추가해줘")
    assert result.category == IntentCategory.TASK
    assert "task_create" in result.tool_hints


def test_contact_intent():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("김철수 연락처 찾아줘")
    assert result.category == IntentCategory.CONTACT
    assert "contact_search" in result.tool_hints


def test_search_files_intent():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("보고서 파일 찾아줘")
    assert result.category == IntentCategory.SEARCH_FILES
    assert "file_search" in result.tool_hints


def test_task_beats_execute():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("할 일 생성해줘")
    assert result.category == IntentCategory.TASK


def test_schedule_beats_execute():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("일정 추가해줘")
    assert result.category == IntentCategory.SCHEDULE


def test_existing_intents_unchanged():
    from breadmind.core.intent import classify, IntentCategory
    result = classify("서버 상태 확인해줘")
    assert result.category == IntentCategory.QUERY
    result = classify("안녕하세요")
    assert result.category == IntentCategory.CHAT
    result = classify("에러가 발생했어 분석해줘")
    assert result.category == IntentCategory.DIAGNOSE


def test_think_budgets_for_new_categories():
    from breadmind.core.intent import classify, get_think_budget, IntentCategory
    schedule = classify("회의 일정 잡아줘")
    assert schedule.category == IntentCategory.SCHEDULE
    budget = get_think_budget(schedule)
    assert budget > 0
