from __future__ import annotations

import pytest


def test_all_pass_reports_go():
    from scripts.check_go_no_go import GoNoGoReport, evaluate

    r: GoNoGoReport = evaluate(
        recall_at_5=0.82, citation_accuracy=0.96, hallucination_rate=0.02,
        sensitive_block_precision=0.92, user_satisfaction=0.78,
        weekly_active_users_ratio=0.8, security_incidents=0,
        p95_latency_seconds=4.2, review_queue_processed_ratio=0.85,
    )
    assert r.decision == "GO"
    assert all(c.passed for c in r.checks)


def test_one_fail_reports_nogo():
    from scripts.check_go_no_go import evaluate

    r = evaluate(
        recall_at_5=0.50, citation_accuracy=0.96, hallucination_rate=0.02,
        sensitive_block_precision=0.92, user_satisfaction=0.78,
        weekly_active_users_ratio=0.8, security_incidents=0,
        p95_latency_seconds=4.2, review_queue_processed_ratio=0.85,
    )
    assert r.decision == "NO_GO"
    failing = [c.name for c in r.checks if not c.passed]
    assert "recall_at_5" in failing


def test_security_incidents_blocks_go():
    from scripts.check_go_no_go import evaluate

    r = evaluate(
        recall_at_5=0.82, citation_accuracy=0.96, hallucination_rate=0.02,
        sensitive_block_precision=0.92, user_satisfaction=0.78,
        weekly_active_users_ratio=0.8, security_incidents=1,
        p95_latency_seconds=4.2, review_queue_processed_ratio=0.85,
    )
    assert r.decision == "NO_GO"


def test_cli_main_exit_code(tmp_path, monkeypatch, capsys):
    import json as _json
    import scripts.check_go_no_go as m

    data = {
        "recall_at_5": 0.82, "citation_accuracy": 0.96, "hallucination_rate": 0.02,
        "sensitive_block_precision": 0.92, "user_satisfaction": 0.78,
        "weekly_active_users_ratio": 0.8, "security_incidents": 0,
        "p95_latency_seconds": 4.2, "review_queue_processed_ratio": 0.85,
    }
    p = tmp_path / "r.json"
    p.write_text(_json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        m.main(["--report", str(p)])
    assert exc.value.code == 0
