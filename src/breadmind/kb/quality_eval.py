"""Weekly quality-regression eval (spec §9.4)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from prometheus_client import CollectorRegistry, Gauge

from breadmind.kb import metrics as kb_metrics

logger = logging.getLogger(__name__)

REPORT_DIR = Path("docs/pilot/quality-reports")

QUALITY_RECALL: Gauge
QUALITY_CITATION: Gauge
QUALITY_HALLUCINATION: Gauge
QUALITY_SENSITIVE_PRECISION: Gauge
QUALITY_SATISFACTION: Gauge


def _ensure_quality_metrics(reg: CollectorRegistry) -> None:
    global QUALITY_RECALL, QUALITY_CITATION, QUALITY_HALLUCINATION
    global QUALITY_SENSITIVE_PRECISION, QUALITY_SATISFACTION
    for name in (
        "breadmind_quality_recall_at_5",
        "breadmind_quality_citation_accuracy",
        "breadmind_quality_hallucination_rate",
        "breadmind_quality_sensitive_precision",
        "breadmind_quality_user_satisfaction",
    ):
        if name in reg._names_to_collectors:  # type: ignore[attr-defined]
            reg.unregister(reg._names_to_collectors[name])  # type: ignore[attr-defined]
    QUALITY_RECALL = Gauge(
        "breadmind_quality_recall_at_5", "Recall@5", registry=reg,
    )
    QUALITY_CITATION = Gauge(
        "breadmind_quality_citation_accuracy", "Citation accuracy", registry=reg,
    )
    QUALITY_HALLUCINATION = Gauge(
        "breadmind_quality_hallucination_rate", "Hallucination rate", registry=reg,
    )
    QUALITY_SENSITIVE_PRECISION = Gauge(
        "breadmind_quality_sensitive_precision",
        "Sensitive-block precision",
        registry=reg,
    )
    QUALITY_SATISFACTION = Gauge(
        "breadmind_quality_user_satisfaction",
        "Thumbs-up / (thumbs-up + thumbs-down) ratio",
        registry=reg,
    )


_ensure_quality_metrics(kb_metrics.REGISTRY)


@dataclass
class EvalCase:
    qid: str
    retrieved_ids: list[str]
    answer_text: str
    cited_ids: list[str]
    blocked: bool = False


@dataclass
class EvalReport:
    recall_at_5: float
    citation_accuracy: float
    hallucination_rate: float
    sensitive_block_precision: float
    user_satisfaction: float


async def _run_case(q: dict) -> EvalCase:
    """Runtime-patched in tests. Real impl boots QueryPipeline.build_for_eval."""
    from breadmind.kb.query_pipeline import QueryPipeline
    pipe = QueryPipeline.build_for_eval()
    result = await pipe.answer(
        user_id=q["user"], project_id=q["project"],
        channel_id=q["channel"], text=q["question"],
    )
    return EvalCase(
        qid=q["id"],
        retrieved_ids=[h.id for h in result.sources[:5]],
        answer_text=result.text,
        cited_ids=getattr(result, "citation_ids", []),
        blocked=bool(q.get("expected_blocked") and "민감" in result.text),
    )


def _recall_at_5(expected: list[str], retrieved: list[str]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for e in expected if e in retrieved[:5])
    return hits / len(expected)


def _cite_accuracy(expected: list[str], cited: list[str]) -> float:
    if not cited and not expected:
        return 1.0
    if not cited:
        return 0.0
    good = sum(1 for c in cited if c in expected or not expected)
    return good / len(cited)


async def run_weekly_eval(goldens_path: str,
                          satisfaction: tuple[int, int]) -> EvalReport:
    data = json.loads(Path(goldens_path).read_text(encoding="utf-8"))
    recalls: list[float] = []
    cites: list[float] = []
    hallucinations = 0
    sensitive_tp = 0
    sensitive_fp = 0

    for q in data:
        case = await _run_case(q)
        if q.get("expected_blocked"):
            if case.blocked:
                sensitive_tp += 1
            else:
                sensitive_fp += 1
            continue
        recalls.append(_recall_at_5(q["expected_source_ids"], case.retrieved_ids))
        cites.append(_cite_accuracy(q["expected_source_ids"], case.cited_ids))
        if (
            case.answer_text.strip()
            and not case.cited_ids
            and q["expected_source_ids"]
        ):
            hallucinations += 1

    ups, total = satisfaction
    report = EvalReport(
        recall_at_5=sum(recalls) / len(recalls) if recalls else 0.0,
        citation_accuracy=sum(cites) / len(cites) if cites else 0.0,
        hallucination_rate=hallucinations / len(recalls) if recalls else 0.0,
        sensitive_block_precision=(
            sensitive_tp / (sensitive_tp + sensitive_fp)
            if (sensitive_tp + sensitive_fp) else 1.0
        ),
        user_satisfaction=ups / total if total else 0.0,
    )
    emit_metrics(report)
    _write_report(report)
    return report


def emit_metrics(r: EvalReport) -> None:
    QUALITY_RECALL.set(r.recall_at_5)
    QUALITY_CITATION.set(r.citation_accuracy)
    QUALITY_HALLUCINATION.set(r.hallucination_rate)
    QUALITY_SENSITIVE_PRECISION.set(r.sensitive_block_precision)
    QUALITY_SATISFACTION.set(r.user_satisfaction)


def _write_report(r: EvalReport) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d-%H%M%S")
    md = REPORT_DIR / f"quality-{stamp}.md"
    js = md.with_suffix(".json")
    md.write_text(
        "# BreadMind KB Quality Report\n\n"
        f"- Recall@5: **{r.recall_at_5:.3f}**\n"
        f"- Citation accuracy: **{r.citation_accuracy:.3f}**\n"
        f"- Hallucination rate: **{r.hallucination_rate:.3f}**\n"
        f"- Sensitive block precision: **{r.sensitive_block_precision:.3f}**\n"
        f"- User satisfaction: **{r.user_satisfaction:.3f}**\n",
        encoding="utf-8",
    )
    js.write_text(json.dumps(asdict(r), indent=2), encoding="utf-8")
    return md


def open_pr(report_path: Path) -> None:
    branch = f"quality-report/{report_path.stem}"
    subprocess.check_call(["git", "checkout", "-b", branch])
    subprocess.check_call([
        "git", "add",
        str(report_path), str(report_path.with_suffix(".json")),
    ])
    subprocess.check_call([
        "git", "commit", "-m", f"chore(quality): {report_path.stem}",
    ])
    subprocess.check_call(["git", "push", "-u", "origin", branch])
    subprocess.check_call([
        "gh", "pr", "create", "--title", f"Quality report {report_path.stem}",
        "--body", report_path.read_text(encoding="utf-8"),
    ])


# ── Celery entrypoint ──────────────────────────────────────────────────

from breadmind.tasks.celery_app import celery_app


@celery_app.task(name="breadmind.kb.quality_eval.weekly")
def weekly_eval_task() -> dict:
    report = asyncio.run(
        run_weekly_eval("tests/e2e/goldens/qa.json", satisfaction=(0, 0))
    )
    return asdict(report)
