from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from breadmind.kb import metrics as m


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    reg = CollectorRegistry()
    monkeypatch.setattr(m, "REGISTRY", reg, raising=True)
    m._build_metrics(reg)
    yield reg


def _val(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


def test_observe_query_increments_counter():
    m.observe_query(project="proj-a", status="ok", confidence="high")
    assert _val(m.QUERY_TOTAL, project="proj-a", status="ok", confidence="high") == 1.0


def test_observe_llm_latency_records_histogram():
    m.observe_llm_latency(provider="anthropic", model="claude-opus", seconds=0.42)
    s = m.LLM_LATENCY.labels(provider="anthropic", model="claude-opus")._sum.get()
    assert s == pytest.approx(0.42)


def test_observe_llm_tokens_tracks_direction():
    m.observe_llm_tokens(provider="azure", direction="input", n=100)
    m.observe_llm_tokens(provider="azure", direction="output", n=25)
    assert _val(m.LLM_TOKENS, provider="azure", direction="input") == 100.0
    assert _val(m.LLM_TOKENS, provider="azure", direction="output") == 25.0


def test_observe_redaction_event():
    m.observe_redaction(pattern="email")
    assert _val(m.REDACTION_EVENTS, pattern="email") == 1.0


def test_set_promotion_backlog_gauge():
    m.set_promotion_backlog(17)
    assert m.PROMOTION_BACKLOG._value.get() == 17.0


def test_set_kb_size_bytes_gauge_per_project():
    m.set_kb_size_bytes(project="proj-a", bytes_=2048)
    assert m.KB_SIZE_BYTES.labels(project="proj-a")._value.get() == 2048.0


def test_observe_block_sensitive():
    m.observe_block_sensitive(category="hr")
    assert _val(m.BLOCK_SENSITIVE, category="hr") == 1.0


def test_time_llm_context_manager_records_latency():
    with m.time_llm("ollama", "llama3"):
        pass
    # prometheus_client stores non-cumulative per-bucket counters in child._buckets;
    # summing them yields the total observation count. The plan's `._count`
    # accessor does not exist on Histogram children in prometheus_client 0.25.
    child = m.LLM_LATENCY.labels(provider="ollama", model="llama3")
    c = sum(b.get() for b in child._buckets)
    assert c == 1


def test_kb_metrics_endpoint_exposes_counter(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from breadmind.web.routes.kb_metrics import router

    app = FastAPI()
    app.include_router(router)
    m.observe_query(project="p", status="ok", confidence="high")
    r = TestClient(app).get("/kb/metrics")
    assert r.status_code == 200
    assert "breadmind_query_total" in r.text


def test_redactor_emits_metric_per_pattern(monkeypatch):
    from breadmind.kb.redactor import Redactor
    r = Redactor.default()
    r.redact_prompt("contact me at alice@example.com with key AKIA1234567890123456")
    from breadmind.kb import metrics
    out_samples = [
        s for m_ in metrics.REDACTION_EVENTS.collect() for s in m_.samples
    ]
    patterns = {s.labels["pattern"] for s in out_samples if s.name.endswith("_total")}
    assert {"email", "api_key"} <= patterns


def test_sensitive_category_increments_block_counter():
    from breadmind.kb.redactor import Redactor
    r = Redactor.default()
    r.check_sensitive("우리 팀 연봉 테이블 알려줘")
    from breadmind.kb import metrics
    samples = [s for m_ in metrics.BLOCK_SENSITIVE.collect() for s in m_.samples]
    cats = {s.labels["category"] for s in samples if s.name.endswith("_total")}
    assert "hr_compensation" in cats


@pytest.mark.asyncio
async def test_query_pipeline_emits_metrics(monkeypatch):
    from breadmind.kb.query_pipeline import QueryPipeline
    pipe = QueryPipeline.build_for_tests()  # factory added by P2

    result = await pipe.answer(
        user_id="u1", project_id="p1", channel_id="C1", text="hello?"
    )
    assert result.confidence in {"high", "medium", "low"}

    from breadmind.kb import metrics
    # Spec filter uses ``breadmind_query_total_total`` but prometheus_client
    # 0.25 leaves counter sample names intact when the metric name already
    # ends with ``_total`` (no double-suffix). Accept either sample name so
    # the assertion is forward-compatible with future client versions.
    samples = {
        tuple(sorted(s.labels.items())): s.value
        for metric in metrics.QUERY_TOTAL.collect()
        for s in metric.samples
        if s.name in {"breadmind_query_total", "breadmind_query_total_total"}
    }
    assert any(
        dict(k).get("project") == "p1" and dict(k).get("status") == "ok"
        for k in samples
    )


@pytest.mark.asyncio
async def test_review_queue_updates_backlog_gauge(monkeypatch):
    from breadmind.kb.review_queue import ReviewQueue
    q = await ReviewQueue.build_for_tests(pending=12)  # factory added by P3
    await q.refresh_backlog_metric()
    from breadmind.kb import metrics
    assert metrics.PROMOTION_BACKLOG._value.get() == 12.0
