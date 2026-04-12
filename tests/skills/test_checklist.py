from breadmind.skills.checklist import ChecklistTracker


def test_start_creates_state():
    tracker = ChecklistTracker()
    state = tracker.start("sess1", "refactor", steps=["write test", "make it pass", "refactor"])
    assert state.skill_name == "refactor"
    assert state.total == 3
    assert state.completed_count == 0
    assert state.current_step == "write test"


def test_advance_marks_steps():
    tracker = ChecklistTracker()
    tracker.start("sess1", "refactor", steps=["a", "b", "c"])
    state = tracker.advance("sess1", "refactor")
    assert state.completed_count == 1
    assert state.current_step == "b"


def test_advance_past_end():
    tracker = ChecklistTracker()
    tracker.start("sess1", "r", steps=["a"])
    tracker.advance("sess1", "r")
    state = tracker.get("sess1", "r")
    assert state.completed_count == 1
    assert state.is_done


def test_session_isolation():
    tracker = ChecklistTracker()
    tracker.start("a", "s", steps=["x", "y"])
    tracker.start("b", "s", steps=["x", "y"])
    tracker.advance("a", "s")
    assert tracker.get("a", "s").completed_count == 1
    assert tracker.get("b", "s").completed_count == 0


def test_clear_session_removes_state():
    tracker = ChecklistTracker()
    tracker.start("s1", "x", steps=["a"])
    tracker.clear_session("s1")
    assert tracker.get("s1", "x") is None


def test_summary_lists_active_checklists():
    tracker = ChecklistTracker()
    tracker.start("s1", "a", steps=["x", "y"])
    tracker.start("s1", "b", steps=["p"])
    summary = tracker.summary("s1")
    assert len(summary) == 2
    names = {s["skill_name"] for s in summary}
    assert names == {"a", "b"}
