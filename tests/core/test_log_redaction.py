"""LogRedactor 및 StructuredFormatter 레닥션 테스트."""
from __future__ import annotations

import json
import logging

import pytest

from breadmind.core.logging import LogRedactor, StructuredFormatter, setup_logging


class TestLogRedactor:
    def test_redact_api_key_pattern(self):
        redactor = LogRedactor()
        text = "Using api_key=sk-abcdefghij1234567890xxxx for auth"
        result = redactor.redact(text)
        assert "sk-abcdefghij1234567890xxxx" not in result
        assert "***API_KEY***" in result or "***REDACTED***" in result

    def test_redact_password(self):
        redactor = LogRedactor()
        text = "password=SuperSecret123!"
        result = redactor.redact(text)
        assert "SuperSecret123!" not in result
        assert "***REDACTED***" in result

    def test_redact_jwt_token(self):
        redactor = LogRedactor()
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123signature"
        text = f"Found JWT {jwt} in header"
        result = redactor.redact(text)
        assert "eyJ" not in result
        assert "***JWT***" in result

    def test_redact_bearer_token(self):
        redactor = LogRedactor()
        text = "bearer=some-long-token-value-here"
        result = redactor.redact(text)
        assert "some-long-token-value-here" not in result
        assert "***REDACTED***" in result

    def test_no_redaction_on_safe_text(self):
        redactor = LogRedactor()
        text = "Processing request for user john with 5 items"
        result = redactor.redact(text)
        assert result == text

    def test_custom_extra_patterns(self):
        redactor = LogRedactor(extra_patterns=[
            (r'ssn=\d{3}-\d{2}-\d{4}', 'ssn=***SSN***'),
        ])
        text = "Found ssn=123-45-6789 in data"
        result = redactor.redact(text)
        assert "123-45-6789" not in result
        assert "***SSN***" in result

    def test_structured_formatter_with_redactor(self):
        redactor = LogRedactor()
        formatter = StructuredFormatter(redactor=redactor)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="api_key=sk-abcdefghijklmnopqrstuvwxyz123",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "sk-abcdefghijklmnopqrstuvwxyz123" not in parsed["message"]

    def test_setup_logging_redact_flag(self):
        setup_logging(level="DEBUG", format_type="json", redact=True)
        root = logging.getLogger()
        handler = root.handlers[0]
        formatter = handler.formatter
        assert isinstance(formatter, StructuredFormatter)
        assert formatter._redactor is not None

        # Cleanup
        setup_logging(level="INFO", format_type="text", redact=False)

    def test_redact_in_json_output(self):
        redactor = LogRedactor()
        formatter = StructuredFormatter(redactor=redactor)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="secret=mysecretvalue connecting",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "mysecretvalue" not in parsed["message"]
        assert "***REDACTED***" in parsed["message"]
