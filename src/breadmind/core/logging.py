"""구조화 로깅 및 요청별 trace ID 전파.

contextvars 기반으로 async 환경에서 안전하게 요청 컨텍스트를 전파하며,
JSON 구조화 로그 포맷을 지원한다.
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class RequestContext:
    """요청별 컨텍스트 정보."""

    trace_id: str = ""
    user: str = ""
    channel: str = ""
    session_id: str = ""


_request_context_var: ContextVar[RequestContext] = ContextVar(
    "request_context", default=RequestContext(),
)


def set_request_context(
    trace_id: str,
    user: str = "",
    channel: str = "",
    session_id: str = "",
) -> RequestContext:
    """요청 컨텍스트를 설정한다."""
    ctx = RequestContext(
        trace_id=trace_id,
        user=user,
        channel=channel,
        session_id=session_id,
    )
    _request_context_var.set(ctx)
    return ctx


def get_request_context() -> RequestContext:
    """현재 요청 컨텍스트를 반환한다."""
    return _request_context_var.get()


def generate_trace_id() -> str:
    """uuid4 hex의 앞 16자리로 trace_id를 생성한다."""
    from breadmind.utils.helpers import generate_short_id
    return generate_short_id(16)


@contextmanager
def with_trace_id(
    trace_id: str | None = None,
    user: str = "",
    channel: str = "",
    session_id: str = "",
):
    """새 trace_id를 생성/설정하고 블록 종료 시 이전 컨텍스트를 복원한다."""
    token = _request_context_var.set(
        RequestContext(
            trace_id=trace_id or generate_trace_id(),
            user=user,
            channel=channel,
            session_id=session_id,
        ),
    )
    try:
        yield get_request_context()
    finally:
        _request_context_var.reset(token)


class LogRedactor:
    """Redacts sensitive data from log messages."""

    DEFAULT_PATTERNS = [
        (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
        (r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
        (r'(?i)(token|bearer)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
        (r'(?i)(authorization)\s*[=:]\s*\S+', r'\1=***REDACTED***'),
        # API key patterns (sk-xxx, xai-xxx, etc.)
        (r'\b(sk-[a-zA-Z0-9]{20,})', '***API_KEY***'),
        (r'\b(xai-[a-zA-Z0-9]{20,})', '***API_KEY***'),
        (r'\b(AIza[a-zA-Z0-9_-]{30,})', '***API_KEY***'),
        # JWT tokens
        (r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+', '***JWT***'),
    ]

    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None) -> None:
        self._patterns = [(re.compile(p), r) for p, r in self.DEFAULT_PATTERNS]
        if extra_patterns:
            self._patterns.extend([(re.compile(p), r) for p, r in extra_patterns])

    def redact(self, text: str) -> str:
        """Apply all redaction patterns to text."""
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text


class StructuredFormatter(logging.Formatter):
    """JSON 구조화 로그 포맷터.

    출력 필드: timestamp, level, logger, message, trace_id, user, channel, extra
    """

    def __init__(
        self,
        *args: Any,
        redactor: LogRedactor | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_request_context()

        message = record.getMessage()
        if self._redactor:
            message = self._redactor.redact(message)

        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        # 컨텍스트 필드 추가 (비어있지 않은 것만)
        if ctx.trace_id:
            log_entry["trace_id"] = ctx.trace_id
        if ctx.user:
            log_entry["user"] = ctx.user
        if ctx.channel:
            log_entry["channel"] = ctx.channel

        # extra 필드: 표준 LogRecord 속성이 아닌 것들
        _standard_attrs = {
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "filename", "module", "pathname", "thread", "threadName",
            "process", "processName", "levelname", "levelno", "message",
            "msecs", "taskName",
        }
        extra = {
            k: v for k, v in record.__dict__.items()
            if k not in _standard_attrs and not k.startswith("_")
        }
        if extra:
            if self._redactor:
                extra = {
                    k: self._redactor.redact(str(v)) if isinstance(v, str) else v
                    for k, v in extra.items()
                }
            log_entry["extra"] = extra

        # 예외 정보
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def setup_logging(
    level: str = "INFO",
    format_type: str = "text",
    redact: bool = False,
) -> None:
    """로깅 초기화.

    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: "json"이면 StructuredFormatter, "text"이면 기본 텍스트 포맷
        redact: True이면 민감 데이터 자동 마스킹 활성화
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 기존 핸들러 제거 (중복 방지)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    redactor = LogRedactor() if redact else None

    if format_type == "json":
        handler.setFormatter(StructuredFormatter(redactor=redactor))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root_logger.addHandler(handler)
