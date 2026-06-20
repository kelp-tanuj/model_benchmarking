"""Kelp eval harness — deterministic core (scorers, aggregation, drift) + measured-call seam."""

from harness.aggregate import aggregate_benchmark, aggregate_reps, per_run_means
from harness.candidate_caller import MockCandidateCaller
from harness.drift import DriftVerdict, drift_check
from harness.scorers import score_item, score_value
from harness.types import (
    Aggregate,
    CandidateCaller,
    DeterministicMetric,
    ItemScore,
    MeasuredResult,
)

__all__ = [
    "Aggregate",
    "CandidateCaller",
    "DeterministicMetric",
    "DriftVerdict",
    "ItemScore",
    "MeasuredResult",
    "MockCandidateCaller",
    "aggregate_benchmark",
    "aggregate_reps",
    "drift_check",
    "per_run_means",
    "score_item",
    "score_value",
]
