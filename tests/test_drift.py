from harness.drift import compute_drift, drift_check
from harness.types import Aggregate


def test_compute_drift_excludes_informational_and_missing_baseline():
    agg = {
        "helpfulness": Aggregate(0.70, 0.68, 0.72, 3),   # below band -> degradation
        "latency_ms": Aggregate(2000, 1900, 2100, 3),    # above band (lower_better) -> degradation
        "cost": Aggregate(0.5, 0.5, 0.5, 3),             # below band (lower_better) -> improvement
        "tokens_in": Aggregate(25, 25, 25, 3),           # informational -> excluded
        "exact_answer": Aggregate(1.0, 1.0, 1.0, 3),     # no baseline -> excluded
    }
    baseline = {
        "helpfulness": {"mean": 0.9, "min": 0.85, "max": 0.95},
        "latency_ms": {"mean": 1300, "min": 1200, "max": 1400},
        "cost": {"mean": 1.0, "min": 0.9, "max": 1.1},
        "tokens_in": {"mean": 175, "min": 175, "max": 175},
    }
    directions = {
        "helpfulness": "higher_better", "latency_ms": "lower_better",
        "cost": "lower_better", "tokens_in": "higher_better",
    }
    out = compute_drift(agg, baseline, directions)
    assert out["helpfulness"] == "degradation"
    assert out["latency_ms"] == "degradation"
    assert out["cost"] == "improvement"
    assert "tokens_in" not in out      # informational, excluded
    assert "exact_answer" not in out   # no baseline, excluded

BAND = Aggregate(mean=0.80, min=0.75, max=0.85, n=3)


def test_in_band_no_alert():
    v = drift_check(0.78, BAND, "higher_better")
    assert v.drift is False and v.direction == "in_band"


def test_higher_better_below_band_alerts():
    v = drift_check(0.70, BAND, "higher_better")
    assert v.drift is True and v.direction == "degradation"


def test_higher_better_improvement_not_alarmed():
    v = drift_check(0.92, BAND, "higher_better")
    assert v.drift is False and v.direction == "improvement"


def test_lower_better_above_band_alerts():
    # e.g. latency/cost: rising above the band is degradation
    cost_band = Aggregate(mean=1.0, min=0.9, max=1.1, n=3)
    v = drift_check(1.3, cost_band, "lower_better")
    assert v.drift is True and v.direction == "degradation"


def test_lower_better_improvement_not_alarmed():
    cost_band = Aggregate(mean=1.0, min=0.9, max=1.1, n=3)
    v = drift_check(0.5, cost_band, "lower_better")
    assert v.drift is False and v.direction == "improvement"


def test_boundary_is_in_band():
    assert drift_check(0.75, BAND, "higher_better").direction == "in_band"
    assert drift_check(0.85, BAND, "higher_better").direction == "in_band"
