"""SafetyGuard 감사 로그: 모든 판정 결과를 기록하고 조회/통계/내보내기를 지원한다."""
from __future__ import annotations

import json
import logging
import os
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """감사 로그 항목."""

    timestamp: datetime
    trace_id: str | None
    user: str
    tool_name: str
    arguments: dict[str, Any]
    verdict: str  # "allow" | "deny" | "approve_required"
    reason: str
    approved: bool | None  # 승인 대기 중이면 None
    duration_ms: float  # 판정 소요 시간(밀리초)


class AuditLog:
    """메모리 내 순환 버퍼 기반 감사 로그 (선택적 파일 영속화 지원)."""

    def __init__(
        self,
        max_entries: int = 1000,
        persist_path: str | None = None,
    ) -> None:
        self._max_entries = max_entries
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._persist_path = persist_path
        self._persist_error = False  # True이면 파일 쓰기 비활성화

        if self._persist_path is not None:
            self._load_persisted()

    def record(self, entry: AuditEntry) -> None:
        """항목 추가 + 구조화 로그 출력 + 파일 영속화."""
        self._entries.append(entry)
        if self._persist_path is not None:
            self._persist_entry(entry)
        logger.info(
            "SafetyAudit verdict=%s tool=%s user=%s reason=%s duration_ms=%.2f",
            entry.verdict,
            entry.tool_name,
            entry.user,
            entry.reason,
            entry.duration_ms,
        )

    def _persist_entry(self, entry: AuditEntry) -> None:
        """단일 항목을 JSONL 파일에 추가한다."""
        if self._persist_error or self._persist_path is None:
            return
        try:
            parent = os.path.dirname(self._persist_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            d = asdict(entry)
            d["timestamp"] = entry.timestamp.isoformat()
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Audit persist write failed, falling back to memory-only: %s", exc)
            self._persist_error = True

    def _load_persisted(self) -> None:
        """파일에서 마지막 max_entries개의 항목을 로드한다."""
        if self._persist_path is None or not os.path.exists(self._persist_path):
            return
        try:
            lines: list[str] = []
            with open(self._persist_path, encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
            # 마지막 max_entries개만 유지
            for raw in lines[-self._max_entries :]:
                try:
                    d = json.loads(raw)
                    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
                    self._entries.append(AuditEntry(**d))
                except (json.JSONDecodeError, TypeError, KeyError) as exc:
                    logger.debug("Skipping malformed audit line: %s", exc)
        except OSError as exc:
            logger.warning("Audit persist load failed, starting empty: %s", exc)

    def rotate(self, max_file_size_mb: int = 10) -> None:
        """파일 크기가 max_file_size_mb를 초과하면 .1로 이름 변경 후 새 파일 시작."""
        if self._persist_path is None or not os.path.exists(self._persist_path):
            return
        try:
            size_mb = os.path.getsize(self._persist_path) / (1024 * 1024)
            if size_mb > max_file_size_mb:
                rotated = self._persist_path + ".1"
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(self._persist_path, rotated)
                logger.info("Audit log rotated: %s -> %s", self._persist_path, rotated)
        except OSError as exc:
            logger.warning("Audit log rotation failed: %s", exc)

    def get_entries(
        self,
        user: str | None = None,
        tool: str | None = None,
        verdict: str | None = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """필터링 조회. 최신 항목부터 반환."""
        results: list[AuditEntry] = []
        for entry in reversed(self._entries):
            if user is not None and entry.user != user:
                continue
            if tool is not None and entry.tool_name != tool:
                continue
            if verdict is not None and entry.verdict != verdict:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_stats(self) -> dict[str, Any]:
        """통계: 총 판정수, 허용/거부/승인 비율, 가장 많이 거부된 도구 등."""
        total = len(self._entries)
        if total == 0:
            return {
                "total": 0,
                "allow": 0,
                "deny": 0,
                "approve_required": 0,
                "allow_ratio": 0.0,
                "deny_ratio": 0.0,
                "approve_required_ratio": 0.0,
                "most_denied_tools": [],
            }

        counts: dict[str, int] = {"allow": 0, "deny": 0, "approve_required": 0}
        deny_by_tool: dict[str, int] = {}

        for entry in self._entries:
            counts[entry.verdict] = counts.get(entry.verdict, 0) + 1
            if entry.verdict == "deny":
                deny_by_tool[entry.tool_name] = deny_by_tool.get(entry.tool_name, 0) + 1

        most_denied = sorted(deny_by_tool.items(), key=lambda x: x[1], reverse=True)

        return {
            "total": total,
            "allow": counts["allow"],
            "deny": counts["deny"],
            "approve_required": counts["approve_required"],
            "allow_ratio": counts["allow"] / total,
            "deny_ratio": counts["deny"] / total,
            "approve_required_ratio": counts["approve_required"] / total,
            "most_denied_tools": [
                {"tool": name, "count": cnt} for name, cnt in most_denied
            ],
        }

    def export_json(self) -> str:
        """JSON 내보내기."""
        entries = []
        for entry in self._entries:
            d = asdict(entry)
            d["timestamp"] = entry.timestamp.isoformat()
            entries.append(d)
        return json.dumps(entries, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        """로그 초기화."""
        self._entries.clear()
