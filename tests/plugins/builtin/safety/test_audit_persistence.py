"""AuditLog 파일 영속화 테스트."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch


from breadmind.plugins.builtin.safety.audit import AuditEntry, AuditLog


def _make_entry(**overrides) -> AuditEntry:
    defaults = {
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "trace_id": "abc123",
        "user": "tester",
        "tool_name": "shell",
        "arguments": {"cmd": "ls"},
        "verdict": "allow",
        "reason": "safe",
        "approved": True,
        "duration_ms": 1.5,
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


class TestAuditPersistence:
    def test_persist_entry_writes_jsonl(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        log = AuditLog(persist_path=path)
        entry = _make_entry()
        log.record(entry)

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["user"] == "tester"
        assert data["tool_name"] == "shell"
        assert data["verdict"] == "allow"
        assert data["timestamp"] == "2025-01-01T12:00:00+00:00"

    def test_load_persisted_on_init(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        # Write some entries manually
        entries = [_make_entry(user=f"user{i}") for i in range(3)]
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                d = {
                    "timestamp": e.timestamp.isoformat(),
                    "trace_id": e.trace_id,
                    "user": e.user,
                    "tool_name": e.tool_name,
                    "arguments": e.arguments,
                    "verdict": e.verdict,
                    "reason": e.reason,
                    "approved": e.approved,
                    "duration_ms": e.duration_ms,
                }
                f.write(json.dumps(d) + "\n")

        log = AuditLog(persist_path=path)
        loaded = log.get_entries(limit=10)
        assert len(loaded) == 3
        assert loaded[0].user == "user2"  # most recent first

    def test_rotate_when_file_exceeds_size(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        # Create a file larger than 1MB
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * (2 * 1024 * 1024))

        log = AuditLog(persist_path=path)
        log.rotate(max_file_size_mb=1)

        assert os.path.exists(path + ".1")
        assert not os.path.exists(path)

    def test_persist_path_none_is_memory_only(self, tmp_path):
        log = AuditLog(persist_path=None)
        log.record(_make_entry())
        assert len(log.get_entries()) == 1
        # No file should be created anywhere

    def test_file_io_error_graceful_fallback(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        log = AuditLog(persist_path=path)

        with patch("builtins.open", side_effect=OSError("disk full")):
            # Should not raise, falls back to memory-only
            log.record(_make_entry())

        assert len(log.get_entries()) == 1
        assert log._persist_error is True

    def test_backward_compat_no_persist(self):
        log = AuditLog(max_entries=5)
        for i in range(3):
            log.record(_make_entry(user=f"u{i}"))
        assert len(log.get_entries(limit=10)) == 3

    def test_creates_parent_directory(self, tmp_path):
        path = str(tmp_path / "sub" / "dir" / "audit.jsonl")
        log = AuditLog(persist_path=path)
        log.record(_make_entry())

        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            assert len(f.readlines()) == 1
