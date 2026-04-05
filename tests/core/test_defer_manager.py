"""Tests for DeferManager (PreToolUse defer / headless pause-resume)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from breadmind.core.defer_manager import (
    DeferManager,
    DeferredToolCall,
    DeferStatus,
)


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    d = tmp_path / "deferred"
    d.mkdir()
    return d


@pytest.fixture
def manager(storage_dir: Path) -> DeferManager:
    return DeferManager(storage_dir=storage_dir)


def _make_tool_call(
    session_id: str = "sess-1",
    tool_name: str = "shell",
    reason: str = "needs approval",
    deferred_at: datetime | None = None,
) -> DeferredToolCall:
    return DeferredToolCall(
        tool_name=tool_name,
        arguments={"cmd": "rm -rf /"},
        deferred_at=deferred_at or datetime.now(timezone.utc),
        session_id=session_id,
        reason=reason,
    )


class TestDeferredToolCallSerialization:
    def test_round_trip(self):
        tc = _make_tool_call()
        data = tc.to_dict()
        restored = DeferredToolCall.from_dict(data)
        assert restored.tool_name == tc.tool_name
        assert restored.session_id == tc.session_id
        assert restored.status == DeferStatus.DEFERRED


class TestDefer:
    def test_defer_creates_file(self, manager: DeferManager, storage_dir: Path):
        tc = _make_tool_call()
        path = manager.defer(tc)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["tool_name"] == "shell"
        assert data["status"] == "deferred"

    def test_get_deferred(self, manager: DeferManager):
        tc = _make_tool_call()
        manager.defer(tc)
        result = manager.get_deferred("sess-1")
        assert result is not None
        assert result.tool_name == "shell"

    def test_get_deferred_missing(self, manager: DeferManager):
        assert manager.get_deferred("no-such") is None


class TestResume:
    def test_resume_marks_resumed(self, manager: DeferManager):
        tc = _make_tool_call()
        manager.defer(tc)
        resumed = manager.resume("sess-1")
        assert resumed is not None
        assert resumed.status == DeferStatus.RESUMED

    def test_resume_not_found(self, manager: DeferManager):
        assert manager.resume("nope") is None

    def test_resume_idempotent(self, manager: DeferManager):
        tc = _make_tool_call()
        manager.defer(tc)
        manager.resume("sess-1")
        # Second resume should return None (already resumed)
        assert manager.resume("sess-1") is None


class TestListPending:
    def test_lists_only_deferred(self, manager: DeferManager):
        manager.defer(_make_tool_call(session_id="a"))
        manager.defer(_make_tool_call(session_id="b"))
        manager.resume("a")
        pending = manager.list_pending()
        assert len(pending) == 1
        assert pending[0].session_id == "b"


class TestExpireOld:
    def test_expire_old_entries(self, manager: DeferManager):
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        tc = _make_tool_call(session_id="old", deferred_at=old_time)
        manager.defer(tc)

        recent = _make_tool_call(session_id="new")
        manager.defer(recent)

        expired_count = manager.expire_old(max_age_hours=24)
        assert expired_count == 1
        assert manager.get_deferred("old") is None
        assert manager.get_deferred("new") is not None

    def test_expire_zero_when_none_old(self, manager: DeferManager):
        manager.defer(_make_tool_call())
        assert manager.expire_old(max_age_hours=24) == 0
