"""SessionManager 단위 테스트."""
from __future__ import annotations

import pytest

from breadmind.cli.session_manager import SessionManager


@pytest.fixture
def mgr(tmp_path):
    return SessionManager(store_dir=str(tmp_path))


# ── save / load ──────────────────────────────────────────────────


class TestSaveAndLoad:
    def test_save_and_load_session(self, mgr: SessionManager):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        mgr.save_session("s1", messages, {"custom": "data"})
        loaded = mgr.load_session("s1")
        assert loaded is not None
        msgs, meta = loaded
        assert len(msgs) == 2
        assert msgs[0]["content"] == "hello"
        assert meta["custom"] == "data"
        assert meta["message_count"] == 2
        assert "created" in meta
        assert "updated" in meta

    def test_load_nonexistent_returns_none(self, mgr: SessionManager):
        assert mgr.load_session("nonexistent") is None

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "sessions"
        mgr = SessionManager(store_dir=str(nested))
        mgr.save_session("s1", [{"role": "user", "content": "hi"}])
        assert nested.exists()
        assert mgr.load_session("s1") is not None


# ── list_sessions ────────────────────────────────────────────────


class TestListSessions:
    def test_list_sessions_sorted_by_recency(self, mgr: SessionManager, tmp_path):
        # 첫 번째 세션 저장
        mgr.save_session("old", [{"role": "user", "content": "old msg"}], {"created": 1000.0, "updated": 1000.0})
        # 파일 수정 시간 차이를 위해 updated 값을 다르게 설정
        mgr.save_session("new", [{"role": "user", "content": "new msg"}], {"created": 2000.0, "updated": 2000.0})

        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["id"] == "new"
        assert sessions[1]["id"] == "old"

    def test_list_sessions_limit(self, mgr: SessionManager):
        for i in range(10):
            mgr.save_session(f"s{i:02d}", [{"role": "user", "content": f"msg{i}"}],
                             {"created": float(i), "updated": float(i)})
        sessions = mgr.list_sessions(limit=3)
        assert len(sessions) == 3

    def test_list_sessions_empty(self, tmp_path):
        mgr = SessionManager(store_dir=str(tmp_path / "empty"))
        sessions = mgr.list_sessions()
        assert sessions == []


# ── get_latest_session ───────────────────────────────────────────


class TestGetLatestSession:
    def test_get_latest_session(self, mgr: SessionManager):
        mgr.save_session("first", [{"role": "user", "content": "a"}], {"created": 100.0, "updated": 100.0})
        mgr.save_session("second", [{"role": "user", "content": "b"}], {"created": 200.0, "updated": 200.0})
        assert mgr.get_latest_session_id() == "second"

    def test_get_latest_session_empty(self, tmp_path):
        mgr = SessionManager(store_dir=str(tmp_path / "empty"))
        assert mgr.get_latest_session_id() is None


# ── delete_session ───────────────────────────────────────────────


class TestDeleteSession:
    def test_delete_session(self, mgr: SessionManager):
        mgr.save_session("to_delete", [{"role": "user", "content": "bye"}])
        assert mgr.delete_session("to_delete") is True
        assert mgr.load_session("to_delete") is None

    def test_delete_nonexistent(self, mgr: SessionManager):
        assert mgr.delete_session("nope") is False
