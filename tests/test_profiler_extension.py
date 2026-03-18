"""Tests for UserProfiler role/domain extension."""


def test_profiler_has_role_field():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    assert hasattr(profiler, "get_role")


def test_default_role_is_auto():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    assert profiler.get_role("new_user") == "auto"


def test_set_and_get_role():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    profiler.set_role("alice", "developer")
    assert profiler.get_role("alice") == "developer"


def test_record_intent_and_determine_role():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    for _ in range(6):
        profiler.record_intent("bob", "execute")
    for _ in range(4):
        profiler.record_intent("bob", "chat")
    role = profiler.determine_role("bob")
    assert role == "developer"


def test_determine_role_general():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    for _ in range(7):
        profiler.record_intent("carol", "schedule")
    for _ in range(3):
        profiler.record_intent("carol", "task")
    role = profiler.determine_role("carol")
    assert role == "general"


def test_get_exposed_domains_developer():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    profiler.set_role("alice", "developer")
    domains = profiler.get_exposed_domains("alice")
    assert "infra" in domains
    assert "tasks" in domains


def test_get_exposed_domains_general():
    from breadmind.memory.profiler import UserProfiler
    profiler = UserProfiler()
    profiler.set_role("bob", "general")
    domains = profiler.get_exposed_domains("bob")
    assert "infra" not in domains
    assert "tasks" in domains
    assert "calendar" in domains
