import pytest

from harness.aggregate import (
    aggregate_benchmark,
    aggregate_reps,
    default_metric_rollup,
    per_run_means,
)
from harness.types import ItemScore


def test_default_metric_rollup():
    results = [
        {"latency_ms": 100.0, "tokens_in": 10, "tokens_out": 2, "cost": 0.001},
        {"latency_ms": 300.0, "tokens_in": 20, "tokens_out": 4, "cost": 0.002},
    ]
    roll = default_metric_rollup(results)
    assert roll["latency_ms"] == 200.0          # mean per-input latency
    assert roll["tokens_in"] == 30.0 and roll["tokens_out"] == 6.0  # totals
    assert roll["cost"] == pytest.approx(0.003)  # total cost of the pass


def test_default_metric_rollup_missing_cost():
    roll = default_metric_rollup([{"latency_ms": 50.0, "tokens_in": 1, "tokens_out": 1, "cost": None}])
    assert "cost" not in roll  # absent rather than fabricated
    assert roll["latency_ms"] == 50.0


def isc(input_id, metric, value):
    return ItemScore(input_id=input_id, metric=metric, mode="semantic", value=value)


def test_per_run_means_over_inputs():
    items = [
        isc("a", "grounding", 1.0),
        isc("b", "grounding", 0.0),
        isc("a", "correctness", 0.5),
        isc("b", "correctness", 1.0),
    ]
    means = per_run_means(items)
    assert means["grounding"] == 0.5
    assert means["correctness"] == 0.75


def test_per_run_means_single_input():
    assert per_run_means([isc("a", "x", 0.8)]) == {"x": 0.8}


def test_aggregate_reps_range_and_identical():
    agg = aggregate_reps([0.6, 0.8, 0.7])
    assert agg.mean == pytest.approx(0.7)
    assert (agg.min, agg.max, agg.n) == (0.6, 0.8, 3)
    flat = aggregate_reps([0.5, 0.5, 0.5])
    assert (flat.mean, flat.min, flat.max) == (0.5, 0.5, 0.5)  # interval collapses to a point


def test_aggregate_reps_empty_raises():
    with pytest.raises(ValueError):
        aggregate_reps([])


def test_aggregate_benchmark_across_reps():
    reps = [
        {"grounding": 0.5, "correctness": 0.75},
        {"grounding": 0.7, "correctness": 0.75},
        {"grounding": 0.6, "correctness": 0.75},
    ]
    out = aggregate_benchmark(reps)
    assert out["grounding"].mean == pytest.approx(0.6)
    assert (out["grounding"].min, out["grounding"].max) == (0.5, 0.7)
    assert (out["correctness"].min, out["correctness"].max) == (0.75, 0.75)
