# tests/sdui/test_settings_index.py
"""Tests for the settings search index (Phase 9)."""
from breadmind.sdui.settings_index import SETTINGS_CATALOGUE, search_settings

_REQUIRED_FIELDS = {"label", "key", "tab", "field_id"}
_VALID_TABS = {
    "quick_start",
    "agent_behavior",
    "integrations",
    "safety",
    "monitoring",
    "memory",
    "advanced",
}


def test_catalogue_entries_have_required_fields():
    for entry in SETTINGS_CATALOGUE:
        assert _REQUIRED_FIELDS <= entry.keys(), f"Missing fields in: {entry}"


def test_catalogue_entries_have_valid_tabs():
    for entry in SETTINGS_CATALOGUE:
        assert entry["tab"] in _VALID_TABS, f"Invalid tab '{entry['tab']}' in: {entry}"


def test_catalogue_not_empty():
    assert len(SETTINGS_CATALOGUE) >= 40


def test_search_empty_query_returns_empty():
    assert search_settings("") == []


def test_search_none_query_returns_empty():
    assert search_settings(None) == []


def test_search_korean_label_match():
    results = search_settings("모델")
    assert len(results) >= 1
    labels = [r["label"] for r in results]
    assert any("모델" in label for label in labels)


def test_search_key_match():
    results = search_settings("llm")
    assert len(results) >= 1
    keys = [r["key"] for r in results]
    assert any("llm" in key for key in keys)


def test_search_case_insensitive():
    results_lower = search_settings("llm")
    results_upper = search_settings("LLM")
    assert len(results_lower) == len(results_upper)


def test_search_results_capped_at_20():
    # Use a very common substring that matches many entries
    results = search_settings("초")
    assert len(results) <= 20


def test_search_specific_korean():
    results = search_settings("프로바이더")
    assert len(results) >= 1
    assert all("tab" in r for r in results)


def test_search_no_match_returns_empty():
    results = search_settings("zzznomatchzzz")
    assert results == []


def test_search_returns_list_of_dicts():
    results = search_settings("로그")
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, dict)
        assert _REQUIRED_FIELDS <= r.keys()


def test_search_timeout_key():
    results = search_settings("system_timeouts")
    assert len(results) >= 1
    assert all(r["tab"] == "advanced" for r in results)


def test_search_memory_tab():
    results = search_settings("memory_gc_config")
    assert len(results) >= 1
    assert all(r["tab"] == "memory" for r in results)
