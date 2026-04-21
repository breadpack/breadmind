"""OpenTelemetry setup for the KB pipeline (spec §8.4).

Spans emitted: kb.retrieve, kb.redact, kb.llm_call, kb.cite, kb.self_review.
Installs FastAPI + asyncpg auto-instrumentation at app startup.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

logger = logging.getLogger(__name__)

_SERVICE_NAME = "breadmind-kb"
_TRACER_NAME = "breadmind.kb"
_FASTAPI_INSTRUMENTED: set[int] = set()
_ASYNCPG_INSTRUMENTED = False


def install_default_provider() -> TracerProvider:
    """Wire a batching Console exporter unless OTLP env vars are set."""
    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def _force_set_tracer_provider(provider) -> None:
    """Force-install a TracerProvider, bypassing OTel's one-shot guard.

    ``opentelemetry.trace.set_tracer_provider`` uses a ``Once`` guard so the
    global provider can only be set a single time per process. Tests need to
    install fresh providers across fixtures, so we override the guarded
    globals directly (safe: only this module touches them in tests).
    """
    # Reset the one-shot guard so future calls to set_tracer_provider also work.
    try:  # pragma: no cover - internal attribute, best-effort
        from opentelemetry.util._once import Once

        trace._TRACER_PROVIDER_SET_ONCE = Once()
    except Exception:
        pass
    trace._TRACER_PROVIDER = provider


def install_test_provider(provider: TracerProvider) -> None:
    _force_set_tracer_provider(provider)


def reset() -> None:
    global _ASYNCPG_INSTRUMENTED
    _FASTAPI_INSTRUMENTED.clear()
    _ASYNCPG_INSTRUMENTED = False
    _force_set_tracer_provider(trace.NoOpTracerProvider())


def install_fastapi(app) -> None:
    if id(app) in _FASTAPI_INSTRUMENTED:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)
    _FASTAPI_INSTRUMENTED.add(id(app))


def install_asyncpg() -> None:
    global _ASYNCPG_INSTRUMENTED
    if _ASYNCPG_INSTRUMENTED:
        return
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    AsyncPGInstrumentor().instrument()
    _ASYNCPG_INSTRUMENTED = True


def _tracer():
    return trace.get_tracer(_TRACER_NAME)


def _span(name: str, **attrs):
    @asynccontextmanager
    async def _cm() -> AsyncIterator[None]:
        with _tracer().start_as_current_span(name) as span:
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(f"kb.{k}", v)
            yield
    return _cm()


def span_retrieve(project: str, query: str):
    return _span("kb.retrieve", project=project, query_length=len(query))


def span_redact(pattern_count: int):
    return _span("kb.redact", pattern_count=pattern_count)


def span_llm_call(provider: str, model: str):
    return _span("kb.llm_call", provider=provider, model=model)


def span_cite(count: int):
    return _span("kb.cite", citation_count=count)


def span_self_review(confidence: str):
    return _span("kb.self_review", confidence=confidence)
