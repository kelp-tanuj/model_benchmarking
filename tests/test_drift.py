from harness.drift import drift_check
from harness.types import Aggregate

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
