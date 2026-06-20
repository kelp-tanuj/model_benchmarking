"""Drift rule (decision #12): flag when a re-run's MEAN falls outside the baseline band,
degradation direction only.

  - higher_better metric  → alert when rerun mean < baseline.min  (a drop below the band)
  - lower_better metric   → alert when rerun mean > baseline.max  (a rise above the band)

Improvements (mean better than the band) are noted, not alarmed. Ordinary run-to-run jitter
inside the band never fires.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from harness.types import Aggregate, MetricDirection

# Informational metrics never trigger a drift alert (raw counts, not quality/cost signals).
INFORMATIONAL = frozenset({"tokens_in", "tokens_out"})


@dataclass(frozen=True)
class DriftVerdict:
    drift: bool                       # True only for degradation outside the band
    direction: str                    # "degradation" | "improvement" | "in_band"
    rerun_mean: float
    baseline: Aggregate


def drift_check(
    rerun_mean: float, baseline: Aggregate, direction: MetricDirection
) -> DriftVerdict:
    if direction == "higher_better":
        if rerun_mean < baseline.min:
            kind = "degradation"
        elif rerun_mean > baseline.max:
            kind = "improvement"
        else:
            kind = "in_band"
    else:  # lower_better (e.g. cost, latency)
        if rerun_mean > baseline.max:
            kind = "degradation"
        elif rerun_mean < baseline.min:
            kind = "improvement"
        else:
            kind = "in_band"
    return DriftVerdict(
        drift=(kind == "degradation"),
        direction=kind,
        rerun_mean=rerun_mean,
        baseline=baseline,
    )


def compute_drift(
    agg: Mapping[str, Aggregate],
    baseline: Mapping[str, dict],
    directions: Mapping[str, MetricDirection],
    informational: frozenset[str] = INFORMATIONAL,
) -> dict[str, str]:
    """Drift verdict per metric vs a baseline band. Skips informational metrics and any metric
    without a baseline. `baseline[metric]` is a dict with mean/min/max."""
    out: dict[str, str] = {}
    for metric, a in agg.items():
        if metric in informational or metric not in baseline:
            continue
        b = baseline[metric]
        band = Aggregate(mean=b["mean"], min=b["min"], max=b["max"], n=0)
        out[metric] = drift_check(
            a.mean, band, directions.get(metric, "higher_better")
        ).direction
    return out
