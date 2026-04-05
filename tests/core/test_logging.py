"""구조화 로깅 및 요청 trace ID 전파 테스트."""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from breadmind.core.logging import (
    RequestContext,
    StructuredFormatter,
    generate_trace_id,
    get_request_context,
    set_request_context,
    setup_logging,
    with_trace_id,
)


class TestStructuredFormatterJson:
    """JSON 구조화 포맷 출력 검증."""

    def test_structured_formatter_json(self) -> None:
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )

        # trace context 설정
        set_request_context(trace_id="abc123", user="tester", channel="cli")

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "hello world"
        assert data["trace_id"] == "abc123"
        assert data["user"] == "tester"
        assert data["channel"] == "cli"
        assert "timestamp" in data

    def test_formatter_without_context(self) -> None:
        """컨텍스트 미설정 시 trace_id 등이 출력되지 않는다."""
        formatter = StructuredFormatter()

        # 빈 컨텍스트로 리셋
        set_request_context(trace_id="", user="", channel="")

        record = logging.LogRecord(
            name="test", level=logging.WARNING,
            pathname="test.py", lineno=1,
            msg="warning msg", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert "trace_id" not in data
        assert "user" not in data
        assert data["level"] == "WARNING"


class TestRequestContextPropagation:
    """contextvars 전파 검증."""

    def test_request_context_propagation(self) -> None:
        ctx = set_request_context(
            trace_id="trace_001",
            user="alice",
            channel="slack",
            session_id="sess_001",
        )

        retrieved = get_request_context()
        assert retrieved.trace_id == "trace_001"
        assert retrieved.user == "alice"
        assert retrieved.channel == "slack"
        assert retrieved.session_id == "sess_001"

    def test_default_context_is_empty(self) -> None:
        """기본 컨텍스트는 빈 문자열."""
        # 새 ContextVar는 default를 반환
        # 다른 테스트의 영향을 받을 수 있으므로 명시적으로 리셋
        set_request_context(trace_id="", user="", channel="", session_id="")
        ctx = get_request_context()
        assert ctx.trace_id == ""
        assert ctx.user == ""


class TestTraceIdGeneration:
    """trace_id 형식 검증."""

    def test_trace_id_generation(self) -> None:
        tid = generate_trace_id()
        assert len(tid) == 16
        # hex 문자만 포함
        assert all(c in "0123456789abcdef" for c in tid)

    def test_trace_ids_are_unique(self) -> None:
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100


class TestWithTraceIdContextManager:
    """context manager 동작 검증."""

    def test_with_trace_id_context_manager(self) -> None:
        set_request_context(trace_id="outer", user="outer_user")

        with with_trace_id(trace_id="inner", user="inner_user") as ctx:
            assert ctx.trace_id == "inner"
            assert ctx.user == "inner_user"
            assert get_request_context().trace_id == "inner"

        # 블록 종료 후 이전 컨텍스트 복원
        restored = get_request_context()
        assert restored.trace_id == "outer"
        assert restored.user == "outer_user"

    def test_with_trace_id_auto_generates(self) -> None:
        """trace_id 미지정 시 자동 생성."""
        with with_trace_id() as ctx:
            assert len(ctx.trace_id) == 16
            assert ctx.trace_id != ""


class TestSetupLoggingJsonFormat:
    """JSON 모드 설정 검증."""

    def test_setup_logging_json_format(self) -> None:
        setup_logging(level="DEBUG", format_type="json")

        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1

        handler = root.handlers[0]
        assert isinstance(handler.formatter, StructuredFormatter)

        # cleanup
        root.handlers.clear()


class TestSetupLoggingTextFormat:
    """텍스트 모드 설정 검증."""

    def test_setup_logging_text_format(self) -> None:
        setup_logging(level="WARNING", format_type="text")

        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1

        handler = root.handlers[0]
        assert not isinstance(handler.formatter, StructuredFormatter)

        # cleanup
        root.handlers.clear()


class TestNestedContexts:
    """중첩 컨텍스트에서 독립성 검증."""

    def test_nested_contexts(self) -> None:
        with with_trace_id(trace_id="level1", user="user1") as ctx1:
            assert ctx1.trace_id == "level1"

            with with_trace_id(trace_id="level2", user="user2") as ctx2:
                assert ctx2.trace_id == "level2"
                assert ctx2.user == "user2"
                assert get_request_context().trace_id == "level2"

            # level2 종료 후 level1 복원
            assert get_request_context().trace_id == "level1"
            assert get_request_context().user == "user1"

        # 모든 블록 종료 후 원래 컨텍스트 복원
        # (이전 테스트에서 설정된 값이 복원됨)


class TestFormatterWithExtraFields:
    """추가 필드 포함 검증."""

    def test_formatter_with_extra_fields(self) -> None:
        formatter = StructuredFormatter()

        set_request_context(trace_id="extra_test")

        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="with extra", args=(), exc_info=None,
        )
        # LogRecord에 커스텀 필드 추가
        record.request_method = "POST"  # type: ignore[attr-defined]
        record.endpoint = "/api/chat"  # type: ignore[attr-defined]

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "with extra"
        assert data["trace_id"] == "extra_test"
        assert "extra" in data
        assert data["extra"]["request_method"] == "POST"
        assert data["extra"]["endpoint"] == "/api/chat"

    def test_formatter_with_exception(self) -> None:
        """예외 정보가 포함된 로그 레코드."""
        formatter = StructuredFormatter()
        set_request_context(trace_id="exc_test")

        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR,
                pathname="test.py", lineno=1,
                msg="error occurred", args=(),
                exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "ERROR"
        assert "exception" in data
        assert "ValueError" in data["exception"]
