"""Deterministic aggregation: item_scores → scores_per_run → scores.

The agent never aggregates — this code does, so quality numbers are reproducible from the
stored per-input values. Two tiers:
  1. per rep: mean of item_scores over inputs, per metric  (scores_per_run)
  2. across reps: mean + observed range over the N reps     (scores)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from harness.types import Aggregate, ItemScore


def per_run_means(item_scores: Sequence[ItemScore]) -> dict[str, float]:
    """One rep's per-metric value = mean of its per-input scores. Returns {metric: mean}."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for s in item_scores:
        buckets[s.metric].append(s.value)
    return {metric: sum(vals) / len(vals) for metric, vals in buckets.items() if vals}


def aggregate_reps(per_rep_values: Sequence[float]) -> Aggregate:
    """Across the N reps for one metric → mean + observed range."""
    if not per_rep_values:
        raise ValueError("aggregate_reps requires at least one rep value")
    vals = list(per_rep_values)
    return Aggregate(mean=sum(vals) / len(vals), min=min(vals), max=max(vals), n=len(vals))


def default_metric_rollup(results: Sequence[dict]) -> dict[str, float]:
    """Roll one rep's per-input results into the default harness metrics for that pass:
    mean per-input latency, total tokens, total cost. Surfaced in `scores` like any metric so
    they appear on the leaderboard/report (the latency/tokens/cost deliverables)."""
    lat = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    costs = [float(r["cost"]) for r in results if r.get("cost") is not None]
    out: dict[str, float] = {
        "tokens_in": float(sum((r.get("tokens_in") or 0) for r in results)),
        "tokens_out": float(sum((r.get("tokens_out") or 0) for r in results)),
    }
    if lat:
        out["latency_ms"] = sum(lat) / len(lat)
    if costs:
        out["cost"] = sum(costs)
    return out


def aggregate_benchmark(
    per_rep_metric_values: Sequence[dict[str, float]],
) -> dict[str, Aggregate]:
    """Given each rep's {metric: mean}, produce {metric: Aggregate} across reps."""
    by_metric: dict[str, list[float]] = defaultdict(list)
    for rep in per_rep_metric_values:
        for metric, value in rep.items():
            by_metric[metric].append(value)
    return {metric: aggregate_reps(vals) for metric, vals in by_metric.items()}
