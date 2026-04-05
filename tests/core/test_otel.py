"""OpenTelemetry integration 테스트."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

from breadmind.core.otel import OTelConfig, OTelIntegration, get_otel, init_otel
import breadmind.core.otel as otel_module


class TestOTelDisabled:
    def test_otel_disabled_is_noop(self):
        otel = OTelIntegration(OTelConfig(enabled=False))
        assert otel.available is False
        # All methods should be no-ops without error
        otel.record_session_start()
        otel.record_tool_call("test", 100.0, True)
        otel.record_token_usage(10, 20, "model")
        otel.record_llm_latency(50.0, "model")
        otel.record_cost(0.01, "model")
        with otel.trace_span("test") as span:
            assert span is None


class TestOTelUnavailable:
    def test_otel_unavailable_graceful(self):
        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.metrics": None,
            "opentelemetry.trace": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.metrics": None,
            "opentelemetry.sdk.trace": None,
        }):
            otel = OTelIntegration(OTelConfig(enabled=True))
            assert otel.available is False
            # Should still work as no-ops
            otel.record_session_start()


class TestOTelWithMocks:
    def _make_otel_with_mocks(self):
        """Create an OTelIntegration with mocked OTel SDK."""
        otel = OTelIntegration(OTelConfig(enabled=False))
        # Manually set up mocks
        otel._available = True
        otel._counters["session_count"] = MagicMock()
        otel._counters["tool_call_count"] = MagicMock()
        otel._counters["token_usage"] = MagicMock()
        otel._counters["cost_usage"] = MagicMock()
        otel._histograms["llm_latency"] = MagicMock()
        otel._histograms["tool_latency"] = MagicMock()
        otel._tracer = MagicMock()
        return otel

    def test_record_session_start(self):
        otel = self._make_otel_with_mocks()
        otel.record_session_start({"env": "test"})
        otel._counters["session_count"].add.assert_called_once_with(1, {"env": "test"})

    def test_record_tool_call(self):
        otel = self._make_otel_with_mocks()
        otel.record_tool_call("shell", 150.0, True, {"extra": "val"})
        otel._counters["tool_call_count"].add.assert_called_once()
        otel._histograms["tool_latency"].record.assert_called_once()

    def test_record_token_usage(self):
        otel = self._make_otel_with_mocks()
        otel.record_token_usage(100, 200, "gpt-4")
        assert otel._counters["token_usage"].add.call_count == 2

    def test_trace_span_context_manager(self):
        otel = self._make_otel_with_mocks()
        mock_span = MagicMock()
        otel._tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        otel._tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)

        with otel.trace_span("test_span", {"key": "val"}) as span:
            assert span is mock_span


class TestOTelSingleton:
    def test_singleton_get_otel(self):
        otel_module._instance = None
        result = get_otel()
        assert isinstance(result, OTelIntegration)
        assert result is get_otel()  # same instance
        otel_module._instance = None  # cleanup

    def test_init_otel_creates_instance(self):
        otel_module._instance = None
        config = OTelConfig(enabled=False, service_name="test-svc")
        result = init_otel(config)
        assert isinstance(result, OTelIntegration)
        assert result._config.service_name == "test-svc"
        assert get_otel() is result
        otel_module._instance = None  # cleanup
