from harness.types import Aggregate


def test_disk_use_cases_includes_fixture():
    from daemon import worker
    assert "fixture_qa" in worker._disk_use_cases()


def test_summary_lines_includes_metrics_and_drift():
    from daemon import worker
    summary = {
        "agg": {"exact_answer": Aggregate(mean=1.0, min=1.0, max=1.0, n=3),
                "latency_ms": Aggregate(mean=1200.0, min=1100.0, max=1300.0, n=3)},
        "drift": {"latency_ms": "degradation", "exact_answer": "in_band"},
    }
    lines = worker._summary_lines(summary)
    assert any("exact_answer" in line for line in lines)
    assert any("degradation" in line for line in lines)
