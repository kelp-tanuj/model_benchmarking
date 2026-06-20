"""Core value types for the eval harness.

These are the reproducible, deterministic data shapes the harness produces and aggregates.
Quality scores live on a 0.0–1.0 scale (binary metrics use 1.0/0.0), per the judge contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

MetricMode = Literal["deterministic", "semantic"]
ComparisonMode = Literal["exact", "field", "schema", "numeric"]
MetricDirection = Literal["higher_better", "lower_better"]


@dataclass(frozen=True)
class DeterministicMetric:
    """Spec for a code-scored metric (from a use-case skill's rubric)."""

    name: str
    comparison: ComparisonMode
    fields: tuple[str, ...] | None = None  # for `field`: which keys to compare
    json_schema: dict | None = None        # for `schema`: a JSON Schema
    tolerance: float = 0.0                  # for `numeric`: absolute tolerance
    rel_tolerance: float = 0.0              # for `numeric`: relative tolerance (fraction)
    normalize: bool = True                  # for `exact`/`field`: strip + casefold strings
    direction: MetricDirection = "higher_better"


@dataclass(frozen=True)
class ItemScore:
    """One per-input, per-metric score. `rationale` is set only for semantic judging."""

    input_id: str
    metric: str
    mode: MetricMode
    value: float
    rationale: str | None = None


@dataclass(frozen=True)
class Aggregate:
    """Mean + observed range across a set of values (per-metric across reps)."""

    mean: float
    min: float
    max: float
    n: int


@dataclass(frozen=True)
class MeasuredResult:
    """What a CandidateCaller returns for one input — numbers come off the wire."""

    output: Any
    latency_ms: float
    tokens_in: int
    tokens_out: int
    cost: float | None  # None == "cost unavailable" (never fabricated)
    call_breakdown: list[dict] = field(default_factory=list)


class CandidateCaller(Protocol):
    """The measured-call seam. Real adapters do a timed HTTP round-trip; the mock returns
    canned data. Either way, code (not the agent) produces the numbers."""

    def call(self, input_id: str, request: dict) -> MeasuredResult: ...
