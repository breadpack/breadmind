"""Tests for auto_recommend module."""

from __future__ import annotations

import pytest

from breadmind.tools.auto_recommend import AutoRecommender, UsageRecord


@pytest.fixture
def recommender() -> AutoRecommender:
    return AutoRecommender(max_history=100)


# -- record_usage --


def test_record_usage(recommender: AutoRecommender):
    recommender.record_usage("shell_exec", success=True)
    assert len(recommender._history) == 1
    assert recommender._history[0].tool_name == "shell_exec"


def test_record_usage_trims_history():
    rec = AutoRecommender(max_history=3)
    for i in range(5):
        rec.record_usage(f"tool_{i}")
    assert len(rec._history) == 3
    assert rec._history[0].tool_name == "tool_2"


# -- get_usage_based_recommendations --


def test_usage_based_recommendations(recommender: AutoRecommender):
    for _ in range(10):
        recommender.record_usage("git_commit")
    recs = recommender.get_usage_based_recommendations(installed=set())
    names = [r.name for r in recs]
    assert "github" in names


def test_usage_based_excludes_installed(recommender: AutoRecommender):
    for _ in range(10):
        recommender.record_usage("git_commit")
    recs = recommender.get_usage_based_recommendations(installed={"github"})
    names = [r.name for r in recs]
    assert "github" not in names


# -- get_failure_based_recommendations --


def test_failure_based_recommendations(recommender: AutoRecommender):
    for _ in range(5):
        recommender.record_usage("web_search", success=False)
    recs = recommender.get_failure_based_recommendations(installed=set())
    names = [r.name for r in recs]
    assert "brave-search" in names or "tavily" in names


# -- get_recommendations (combined) --


def test_get_recommendations_deduplicates(recommender: AutoRecommender):
    for _ in range(10):
        recommender.record_usage("web_search", success=True)
    for _ in range(5):
        recommender.record_usage("web_search", success=False)
    recs = recommender.get_recommendations(installed=set())
    name_counts = {}
    for r in recs:
        name_counts[r.name] = name_counts.get(r.name, 0) + 1
    # Each name should appear at most once.
    assert all(c == 1 for c in name_counts.values())


def test_get_recommendations_respects_limit(recommender: AutoRecommender):
    for _ in range(10):
        recommender.record_usage("web_search")
        recommender.record_usage("git_commit")
        recommender.record_usage("file_read")
    recs = recommender.get_recommendations(limit=2)
    assert len(recs) <= 2


# -- dismiss --


def test_dismiss_hides_recommendation(recommender: AutoRecommender):
    for _ in range(10):
        recommender.record_usage("git_commit")
    recommender.dismiss("github")
    recs = recommender.get_recommendations(installed=set())
    names = [r.name for r in recs]
    assert "github" not in names


# -- detect_project_type --


def test_detect_project_type_python(recommender: AutoRecommender):
    types = recommender.detect_project_type(["main.py", "requirements.txt"])
    assert "python" in types


def test_detect_project_type_javascript(recommender: AutoRecommender):
    types = recommender.detect_project_type(["index.ts", "package.json"])
    assert "javascript" in types


def test_detect_project_type_docker(recommender: AutoRecommender):
    types = recommender.detect_project_type(["Dockerfile"])
    assert "docker" in types


def test_detect_project_type_empty(recommender: AutoRecommender):
    assert recommender.detect_project_type(None) == []
    assert recommender.detect_project_type([]) == []


# -- get_project_recommendations --


def test_project_recommendations(recommender: AutoRecommender):
    recs = recommender.get_project_recommendations(["python"], installed=set())
    names = [r.name for r in recs]
    assert "python-lsp" in names


# -- statistics --


def test_get_usage_stats_empty(recommender: AutoRecommender):
    stats = recommender.get_usage_stats()
    assert stats["total_calls"] == 0
    assert stats["success_rate"] == 0.0


def test_get_usage_stats_with_data(recommender: AutoRecommender):
    recommender.record_usage("a", success=True)
    recommender.record_usage("a", success=True)
    recommender.record_usage("b", success=False)
    stats = recommender.get_usage_stats()
    assert stats["total_calls"] == 3
    assert stats["unique_tools"] == 2
    assert stats["success_rate"] == pytest.approx(0.67, abs=0.01)


def test_get_top_tools(recommender: AutoRecommender):
    for _ in range(5):
        recommender.record_usage("alpha")
    for _ in range(3):
        recommender.record_usage("beta")
    top = recommender.get_top_tools(limit=2)
    assert top[0] == ("alpha", 5)
    assert top[1] == ("beta", 3)


def test_get_failure_rate(recommender: AutoRecommender):
    recommender.record_usage("x", success=True)
    recommender.record_usage("x", success=False)
    recommender.record_usage("y", success=False)
    rates = recommender.get_failure_rate()
    assert rates["x"] == 0.5
    assert rates["y"] == 1.0
