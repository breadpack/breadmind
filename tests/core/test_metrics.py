"""Tests for breadmind.core.metrics – Prometheus-compatible metrics registry."""
from __future__ import annotations

from breadmind.core.metrics import MetricType, MetricsRegistry, normalize_path


def _make_registry() -> MetricsRegistry:
    return MetricsRegistry()


# ── Counter ───────────────────────────────────────────────────────────


def test_counter_increment():
    r = _make_registry()
    r.counter("requests_total", "Total requests")
    r.counter("requests_total", "Total requests")
    r.counter("requests_total", "Total requests", value=3.0)

    data = r.format_json()
    assert data["requests_total"]["samples"][0]["value"] == 5.0


# ── Gauge ─────────────────────────────────────────────────────────────


def test_gauge_set():
    r = _make_registry()
    r.gauge("temperature", "Current temp", value=36.6)
    assert r.format_json()["temperature"]["samples"][0]["value"] == 36.6

    # Overwrite
    r.gauge("temperature", "Current temp", value=37.0)
    assert r.format_json()["temperature"]["samples"][0]["value"] == 37.0


# ── Histogram ─────────────────────────────────────────────────────────


def test_histogram_observe():
    r = _make_registry()
    r.histogram_observe("duration", "Duration", value=0.05, buckets=(0.01, 0.1, 1.0))
    r.histogram_observe("duration", "Duration", value=0.5, buckets=(0.01, 0.1, 1.0))
    r.histogram_observe("duration", "Duration", value=0.005, buckets=(0.01, 0.1, 1.0))

    data = r.format_json()
    h = data["duration"]["samples"][0]
    assert h["count"] == 3
    assert abs(h["sum"] - 0.555) < 1e-9
    # 0.005 <= 0.01, so bucket "0.01" = 1
    # 0.005 and 0.05 <= 0.1, so bucket "0.1" = 2
    # all three <= 1.0, so bucket "1" = 3
    assert h["buckets"]["0.01"] == 1
    assert h["buckets"]["0.1"] == 2
    assert h["buckets"]["1"] == 3
    assert h["buckets"]["+Inf"] == 3


def test_histogram_buckets():
    """Verify custom bucket boundaries produce correct distributions."""
    r = _make_registry()
    buckets = (0.1, 0.5, 1.0, 5.0, 10.0)
    values = [0.05, 0.2, 0.8, 3.0, 7.0, 15.0]
    for v in values:
        r.histogram_observe("latency", "Latency", value=v, buckets=buckets)

    data = r.format_json()
    h = data["latency"]["samples"][0]
    assert h["count"] == 6
    # 0.05 <= 0.1
    assert h["buckets"]["0.1"] == 1
    # 0.05, 0.2 <= 0.5
    assert h["buckets"]["0.5"] == 2
    # + 0.8 <= 1.0
    assert h["buckets"]["1"] == 3
    # + 3.0 <= 5.0
    assert h["buckets"]["5"] == 4
    # + 7.0 <= 10.0
    assert h["buckets"]["10"] == 5
    # +Inf includes all
    assert h["buckets"]["+Inf"] == 6


# ── Prometheus format ─────────────────────────────────────────────────


def test_format_prometheus():
    r = _make_registry()
    r.counter(
        "breadmind_requests_total", "Total HTTP requests",
        labels={"method": "GET", "path": "/api/chat"},
    )

    output = r.format_prometheus()
    assert '# HELP breadmind_requests_total Total HTTP requests' in output
    assert '# TYPE breadmind_requests_total counter' in output
    assert 'breadmind_requests_total{method="GET",path="/api/chat"} 1' in output


def test_format_prometheus_histogram():
    r = _make_registry()
    r.histogram_observe(
        "req_duration", "Request duration", value=0.25, buckets=(0.1, 0.5, 1.0),
    )

    output = r.format_prometheus()
    assert '# TYPE req_duration histogram' in output
    assert 'req_duration_bucket{le="0.1"} 0' in output
    assert 'req_duration_bucket{le="0.5"} 1' in output
    assert 'req_duration_bucket{le="1"} 1' in output
    assert 'req_duration_bucket{le="+Inf"} 1' in output
    assert 'req_duration_sum' in output
    assert 'req_duration_count' in output


# ── JSON format ───────────────────────────────────────────────────────


def test_format_json():
    r = _make_registry()
    r.counter("rpc_calls", "Total RPC calls")
    r.gauge("queue_size", "Queue size", value=42)

    data = r.format_json()

    assert data["rpc_calls"]["type"] == "counter"
    assert data["rpc_calls"]["samples"][0]["value"] == 1.0

    assert data["queue_size"]["type"] == "gauge"
    assert data["queue_size"]["samples"][0]["value"] == 42


# ── Labels ────────────────────────────────────────────────────────────


def test_labels():
    r = _make_registry()
    r.counter("http_total", "HTTP total", labels={"method": "GET", "code": "200"})
    r.counter("http_total", "HTTP total", labels={"method": "POST", "code": "201"})
    r.counter("http_total", "HTTP total", labels={"method": "GET", "code": "200"}, value=2)

    data = r.format_json()
    samples = data["http_total"]["samples"]
    assert len(samples) == 2

    get_sample = next(s for s in samples if s["labels"]["method"] == "GET")
    post_sample = next(s for s in samples if s["labels"]["method"] == "POST")

    assert get_sample["value"] == 3.0  # 1 + 2
    assert post_sample["value"] == 1.0

    # Prometheus format should contain both label sets
    output = r.format_prometheus()
    assert 'method="GET"' in output
    assert 'method="POST"' in output


# ── Metric types ──────────────────────────────────────────────────────


def test_metric_types():
    r = _make_registry()
    r.counter("c", "A counter")
    r.gauge("g", "A gauge", value=1)
    r.histogram_observe("h", "A histogram", value=0.1, buckets=(0.5,))

    data = r.format_json()
    assert data["c"]["type"] == "counter"
    assert data["g"]["type"] == "gauge"
    assert data["h"]["type"] == "histogram"

    output = r.format_prometheus()
    assert "# TYPE c counter" in output
    assert "# TYPE g gauge" in output
    assert "# TYPE h histogram" in output


# ── Multiple metrics ──────────────────────────────────────────────────


def test_multiple_metrics():
    r = _make_registry()

    r.counter("req_total", "Requests", labels={"path": "/a"})
    r.counter("req_total", "Requests", labels={"path": "/b"}, value=5)
    r.gauge("active", "Active conns", value=10)
    r.gauge("memory_bytes", "Memory", value=1024.0)
    r.histogram_observe("latency_s", "Latency", value=0.1, buckets=(0.05, 0.1, 0.5))
    r.histogram_observe("latency_s", "Latency", value=0.03, buckets=(0.05, 0.1, 0.5))

    data = r.format_json()
    assert len(data) == 4  # 4 distinct metric names

    output = r.format_prometheus()
    # Should have 4 HELP lines
    assert output.count("# HELP") == 4
    assert output.count("# TYPE") == 4


# ── Path normalization ────────────────────────────────────────────────


def test_normalize_path():
    assert normalize_path("/api/v1/chat/123") == "/api/v1/chat/{id}"
    assert normalize_path("/api/v1/job/550e8400-e29b-41d4-a716-446655440000") == "/api/v1/job/{uuid}"
    assert normalize_path("/api/v1/users/42/posts/99") == "/api/v1/users/{id}/posts/{id}"
    assert normalize_path("/health") == "/health"
    assert normalize_path("/api/v1/chat") == "/api/v1/chat"
