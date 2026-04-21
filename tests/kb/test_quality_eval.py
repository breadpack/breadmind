"""Weekly quality-regression eval + Prometheus gauge tests (spec §9.4)."""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_quality_eval_produces_report_and_metrics(tmp_path, monkeypatch):
    from breadmind.kb import quality_eval

    monkeypatch.setattr(quality_eval, "REPORT_DIR", tmp_path)

    async def _fake_run(q):
        return quality_eval.EvalCase(
            qid=q["id"],
            retrieved_ids=q["expected_source_ids"] if int(q["id"][1:]) % 2 else [],
            answer_text="ok" if int(q["id"][1:]) % 2 else "unknown",
            cited_ids=q["expected_source_ids"] if int(q["id"][1:]) % 2 else [],
            blocked=bool(q.get("expected_blocked")),
        )

    monkeypatch.setattr(quality_eval, "_run_case", _fake_run)

    report = await quality_eval.run_weekly_eval(
        goldens_path="tests/e2e/goldens/qa.json",
        satisfaction=(7, 10),
    )
    assert 0.0 <= report.recall_at_5 <= 1.0
    assert 0.0 <= report.citation_accuracy <= 1.0
    assert report.hallucination_rate <= 1.0
    assert report.user_satisfaction == 0.7

    md = list(tmp_path.glob("*.md"))
    assert md
    data = json.loads(md[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert "recall_at_5" in data


def test_emit_prometheus_metrics_updates_gauges(monkeypatch):
    from breadmind.kb import metrics, quality_eval
    from prometheus_client import CollectorRegistry
    metrics._build_metrics(CollectorRegistry())
    quality_eval._ensure_quality_metrics(metrics.REGISTRY)

    r = quality_eval.EvalReport(
        recall_at_5=0.82, citation_accuracy=0.95,
        hallucination_rate=0.02, sensitive_block_precision=0.91,
        user_satisfaction=0.78,
    )
    quality_eval.emit_metrics(r)
    assert quality_eval.QUALITY_RECALL._value.get() == pytest.approx(0.82)
    assert quality_eval.QUALITY_SATISFACTION._value.get() == pytest.approx(0.78)
