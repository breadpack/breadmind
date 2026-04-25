"""OpenTelemetry integration for BreadMind.

Provides native OTel metric/trace/log export when the opentelemetry-api
package is available, falling back gracefully when it is not installed.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OTelConfig:
    """OTel configuration."""

    enabled: bool = False
    service_name: str = "breadmind"
    endpoint: str = ""  # OTLP endpoint (e.g. "http://localhost:4317")
    export_metrics: bool = True
    export_traces: bool = True
    log_user_prompts: bool = False  # privacy: disabled by default
    log_tool_details: bool = False


class OTelIntegration:
    """OpenTelemetry integration with graceful degradation.

    If opentelemetry-api is not installed, all methods are no-ops.
    """

    def __init__(self, config: OTelConfig | None = None) -> None:
        self._config = config or OTelConfig()
        self._available = False
        self._meter = None
        self._tracer = None
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

        if self._config.enabled:
            self._try_init()

    def _try_init(self) -> None:
        """Try to initialize OTel. No-op if packages not available."""
        try:
            from opentelemetry import metrics, trace
            from opentelemetry.sdk.metrics import MeterProvider  # noqa: F401
            from opentelemetry.sdk.trace import TracerProvider  # noqa: F401

            self._meter = metrics.get_meter(self._config.service_name)
            self._tracer = trace.get_tracer(self._config.service_name)
            self._available = True

            # Pre-create standard counters
            self._counters["session_count"] = self._meter.create_counter(
                "breadmind.session.count", description="Sessions started")
            self._counters["tool_call_count"] = self._meter.create_counter(
                "breadmind.tool_call.count", description="Tool calls executed")
            self._counters["token_usage"] = self._meter.create_counter(
                "breadmind.token.usage", description="Tokens used")
            self._counters["cost_usage"] = self._meter.create_counter(
                "breadmind.cost.usage", description="Cost in USD", unit="usd")

            self._histograms["llm_latency"] = self._meter.create_histogram(
                "breadmind.llm.latency", description="LLM call latency", unit="ms")
            self._histograms["tool_latency"] = self._meter.create_histogram(
                "breadmind.tool.latency", description="Tool execution latency", unit="ms")

            logger.info("OpenTelemetry initialized: service=%s", self._config.service_name)
        except ImportError:
            logger.debug("OpenTelemetry packages not installed, metrics disabled")
        except Exception as e:
            logger.warning("OpenTelemetry init failed: %s", e)

    @property
    def available(self) -> bool:
        return self._available

    def record_session_start(self, attributes: dict[str, str] | None = None) -> None:
        if not self._available:
            return
        self._counters["session_count"].add(1, attributes or {})

    def record_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        attributes: dict[str, str] | None = None,
    ) -> None:
        if not self._available:
            return
        attrs = {"tool": tool_name, "success": str(success)}
        if attributes:
            attrs.update(attributes)
        self._counters["tool_call_count"].add(1, attrs)
        self._histograms["tool_latency"].record(duration_ms, attrs)

    def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
        attributes: dict[str, str] | None = None,
    ) -> None:
        if not self._available:
            return
        attrs = {"model": model, "type": "input"}
        if attributes:
            attrs.update(attributes)
        self._counters["token_usage"].add(input_tokens, {**attrs, "type": "input"})
        self._counters["token_usage"].add(output_tokens, {**attrs, "type": "output"})

    def record_llm_latency(
        self,
        duration_ms: float,
        model: str = "",
        attributes: dict[str, str] | None = None,
    ) -> None:
        if not self._available:
            return
        attrs = {"model": model}
        if attributes:
            attrs.update(attributes)
        self._histograms["llm_latency"].record(duration_ms, attrs)

    def record_cost(self, cost_usd: float, model: str = "") -> None:
        if not self._available:
            return
        self._counters["cost_usage"].add(cost_usd, {"model": model})

    @contextmanager
    def trace_span(self, name: str, attributes: dict[str, str] | None = None):
        """Create a trace span. No-op if OTel not available."""
        if not self._available or self._tracer is None:
            yield None
            return
        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span


# Singleton
_instance: OTelIntegration | None = None


def get_otel() -> OTelIntegration:
    global _instance
    if _instance is None:
        _instance = OTelIntegration()
    return _instance


def init_otel(config: OTelConfig) -> OTelIntegration:
    global _instance
    _instance = OTelIntegration(config)
    return _instance


# ---------------------------------------------------------------------------
# Lightweight span helper (T13)
#
# ``OTelIntegration.trace_span`` requires an initialized integration instance;
# the recorder/store call sites prefer a free function so they don't have to
# carry a config-aware singleton around. This helper mirrors the pattern in
# :mod:`breadmind.metrics`: it asks opentelemetry-api for a tracer (which
# returns a no-op tracer when no provider is configured, the default state)
# and falls back to a synchronous no-op context manager when the package
# is missing entirely. Safe to call from anywhere; never raises.
# ---------------------------------------------------------------------------


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401
        return None

    def record_exception(self, exc: BaseException) -> None:  # noqa: D401
        return None


class _NoopTracer:
    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()


try:  # pragma: no cover - exercised whenever opentelemetry-api is installed
    from opentelemetry import trace as _otel_trace

    _memory_tracer: Any = _otel_trace.get_tracer("breadmind.memory")
except Exception:  # pragma: no cover - defensive stub path
    _memory_tracer = _NoopTracer()


def with_span(name: str, attributes: dict[str, str] | None = None):
    """Return a context manager that opens an OTel span named ``name``.

    Falls back to a no-op span when opentelemetry-api is not installed or
    no TracerProvider is configured. The returned object always supports
    ``__enter__``/``__exit__``, ``set_attribute``, and ``record_exception``.
    """
    return _memory_tracer.start_as_current_span(name, attributes=attributes or {})

