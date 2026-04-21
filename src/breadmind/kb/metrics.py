"""Prometheus metrics for the Company KB (spec §8.4).

All metric names are locked by the spec and must not be renamed.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import REGISTRY as DEFAULT_REGISTRY  # noqa: N811
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0)

REGISTRY: CollectorRegistry = DEFAULT_REGISTRY
QUERY_TOTAL: Counter
LLM_LATENCY: Histogram
LLM_TOKENS: Counter
REDACTION_EVENTS: Counter
PROMOTION_BACKLOG: Gauge
KB_SIZE_BYTES: Gauge
BLOCK_SENSITIVE: Counter


def _build_metrics(reg: CollectorRegistry) -> None:
    global REGISTRY, QUERY_TOTAL, LLM_LATENCY, LLM_TOKENS, REDACTION_EVENTS
    global PROMOTION_BACKLOG, KB_SIZE_BYTES, BLOCK_SENSITIVE
    REGISTRY = reg
    QUERY_TOTAL = Counter(
        "breadmind_query_total",
        "Total KB queries served",
        ("project", "status", "confidence"),
        registry=reg,
    )
    LLM_LATENCY = Histogram(
        "breadmind_llm_latency_seconds",
        "LLM call wall-clock latency",
        ("provider", "model"),
        buckets=_LATENCY_BUCKETS,
        registry=reg,
    )
    LLM_TOKENS = Counter(
        "breadmind_llm_tokens_total",
        "LLM tokens consumed (cost core metric)",
        ("provider", "direction"),
        registry=reg,
    )
    REDACTION_EVENTS = Counter(
        "breadmind_redaction_events_total",
        "Redaction events by pattern",
        ("pattern",),
        registry=reg,
    )
    PROMOTION_BACKLOG = Gauge(
        "breadmind_promotion_backlog",
        "Pending promotion candidates",
        registry=reg,
    )
    KB_SIZE_BYTES = Gauge(
        "breadmind_kb_size_bytes",
        "Total stored org_knowledge body bytes per project",
        ("project",),
        registry=reg,
    )
    BLOCK_SENSITIVE = Counter(
        "breadmind_block_sensitive_total",
        "Queries blocked by sensitive-category guard",
        ("category",),
        registry=reg,
    )


_build_metrics(DEFAULT_REGISTRY)


def observe_query(project: str, status: str, confidence: str) -> None:
    QUERY_TOTAL.labels(project=project, status=status, confidence=confidence).inc()


def observe_llm_latency(provider: str, model: str, seconds: float) -> None:
    LLM_LATENCY.labels(provider=provider, model=model).observe(seconds)


def observe_llm_tokens(provider: str, direction: str, n: int) -> None:
    """direction = 'input' | 'output'."""
    LLM_TOKENS.labels(provider=provider, direction=direction).inc(n)


def observe_redaction(pattern: str) -> None:
    REDACTION_EVENTS.labels(pattern=pattern).inc()


def set_promotion_backlog(n: int) -> None:
    PROMOTION_BACKLOG.set(n)


def set_kb_size_bytes(project: str, bytes_: int) -> None:
    KB_SIZE_BYTES.labels(project=project).set(bytes_)


def observe_block_sensitive(category: str) -> None:
    BLOCK_SENSITIVE.labels(category=category).inc()


@contextmanager
def time_llm(provider: str, model: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        observe_llm_latency(provider, model, time.perf_counter() - start)
