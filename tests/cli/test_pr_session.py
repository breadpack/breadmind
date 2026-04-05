"""PRSessionManager unit tests."""
from __future__ import annotations

import pytest

from breadmind.cli.pr_session import PRSessionLink, PRSessionManager


@pytest.fixture
def mgr(tmp_path):
    return PRSessionManager(storage_dir=tmp_path)


class TestLink:
    def test_link_creates_entry(self, mgr: PRSessionManager):
        link = mgr.link(42, "sess-abc", pr_url="https://github.com/o/r/pull/42", repo="o/r")
        assert link.pr_number == 42
        assert link.session_id == "sess-abc"
        assert link.pr_url == "https://github.com/o/r/pull/42"
        assert link.repo == "o/r"
        assert link.created_at > 0

    def test_link_overwrites_existing(self, mgr: PRSessionManager):
        mgr.link(10, "sess-1")
        mgr.link(10, "sess-2")
        result = mgr.get_session(10)
        assert result is not None
        assert result.session_id == "sess-2"


class TestGetSession:
    def test_get_by_int(self, mgr: PRSessionManager):
        mgr.link(7, "s7")
        assert mgr.get_session(7) is not None
        assert mgr.get_session(7).session_id == "s7"

    def test_get_by_string_number(self, mgr: PRSessionManager):
        mgr.link(99, "s99")
        assert mgr.get_session("99").session_id == "s99"

    def test_get_by_github_url(self, mgr: PRSessionManager):
        mgr.link(123, "s123")
        result = mgr.get_session("https://github.com/owner/repo/pull/123")
        assert result is not None
        assert result.session_id == "s123"

    def test_get_nonexistent_returns_none(self, mgr: PRSessionManager):
        assert mgr.get_session(999) is None

    def test_get_invalid_ref_returns_none(self, mgr: PRSessionManager):
        assert mgr.get_session("not-a-number-or-url") is None


class TestUnlink:
    def test_unlink_existing(self, mgr: PRSessionManager):
        mgr.link(5, "s5")
        assert mgr.unlink(5) is True
        assert mgr.get_session(5) is None

    def test_unlink_nonexistent_returns_false(self, mgr: PRSessionManager):
        assert mgr.unlink(999) is False


class TestListLinks:
    def test_list_sorted_by_creation(self, mgr: PRSessionManager):
        mgr.link(1, "s1")
        mgr.link(2, "s2")
        mgr.link(3, "s3")
        links = mgr.list_links()
        assert len(links) == 3
        # newest first
        assert links[0].pr_number == 3


class TestPersistence:
    def test_data_survives_reload(self, tmp_path):
        mgr1 = PRSessionManager(storage_dir=tmp_path)
        mgr1.link(50, "sess-50", pr_url="https://github.com/x/y/pull/50")

        mgr2 = PRSessionManager(storage_dir=tmp_path)
        result = mgr2.get_session(50)
        assert result is not None
        assert result.session_id == "sess-50"
        assert result.pr_url == "https://github.com/x/y/pull/50"

    def test_corrupt_file_handled_gracefully(self, tmp_path):
        (tmp_path / "pr_links.json").write_text("NOT JSON", encoding="utf-8")
        mgr = PRSessionManager(storage_dir=tmp_path)
        assert mgr.list_links() == []


class TestParseRef:
    def test_parse_int(self, mgr: PRSessionManager):
        assert mgr._parse_pr_ref(42) == 42

    def test_parse_string_digit(self, mgr: PRSessionManager):
        assert mgr._parse_pr_ref("123") == 123

    def test_parse_url(self, mgr: PRSessionManager):
        assert mgr._parse_pr_ref("https://github.com/a/b/pull/77") == 77

    def test_parse_invalid(self, mgr: PRSessionManager):
        assert mgr._parse_pr_ref("hello") is None
