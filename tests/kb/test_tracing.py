# tests/kb/test_tracing.py
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from breadmind.kb import tracing


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    tracing.install_test_provider(provider)
    yield exp
    tracing.reset()


@pytest.mark.asyncio
async def test_span_kb_retrieve_emitted(exporter):
    async with tracing.span_retrieve(project="p", query="q"):
        pass
    names = [s.name for s in exporter.get_finished_spans()]
    assert "kb.retrieve" in names


@pytest.mark.asyncio
async def test_span_kb_redact_llm_cite_self_review(exporter):
    async with tracing.span_redact(pattern_count=3):
        pass
    async with tracing.span_llm_call(provider="anthropic", model="claude-opus"):
        pass
    async with tracing.span_cite(count=5):
        pass
    async with tracing.span_self_review(confidence="high"):
        pass
    names = {s.name for s in exporter.get_finished_spans()}
    assert names >= {"kb.redact", "kb.llm_call", "kb.cite", "kb.self_review"}


def test_install_fastapi_idempotent():
    from fastapi import FastAPI
    app = FastAPI()
    tracing.install_fastapi(app)
    tracing.install_fastapi(app)  # second call must not raise
