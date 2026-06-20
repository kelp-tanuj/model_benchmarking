"""Deterministic scorers — code-scored metrics, fully reproducible (no LLM).

Each returns a float in [0.0, 1.0]. These are the metrics the brief mandates stay as code:
exact match, field-by-field equality, schema validation, numeric tolerance.
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft7Validator

from harness.types import DeterministicMetric, ItemScore


def _norm(v: Any, normalize: bool) -> Any:
    if normalize and isinstance(v, str):
        return v.strip().casefold()
    return v


def _as_obj(v: Any) -> dict | None:
    """Coerce a candidate output to a dict for field/schema scoring; None if impossible."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _score_exact(output: Any, reference: Any, m: DeterministicMetric) -> float:
    return 1.0 if _norm(output, m.normalize) == _norm(reference, m.normalize) else 0.0


def _score_field(output: Any, reference: Any, m: DeterministicMetric) -> float:
    out, ref = _as_obj(output), _as_obj(reference)
    if out is None or ref is None:
        return 0.0
    keys = list(m.fields) if m.fields else list(ref.keys())
    if not keys:
        return 0.0
    matched = sum(
        1
        for k in keys
        if k in ref and _norm(out.get(k), m.normalize) == _norm(ref.get(k), m.normalize)
    )
    return matched / len(keys)


def _score_schema(output: Any, reference: Any, m: DeterministicMetric) -> float:
    schema = m.json_schema if m.json_schema is not None else reference
    if not isinstance(schema, dict):
        return 0.0
    instance = _as_obj(output) if isinstance(output, str) else output
    return 1.0 if not list(Draft7Validator(schema).iter_errors(instance)) else 0.0


def _score_numeric(output: Any, reference: Any, m: DeterministicMetric) -> float:
    try:
        out_v = float(output)
        ref_v = float(reference)
    except (TypeError, ValueError):
        return 0.0
    allowed = m.tolerance + m.rel_tolerance * abs(ref_v)
    return 1.0 if abs(out_v - ref_v) <= allowed else 0.0


_DISPATCH = {
    "exact": _score_exact,
    "field": _score_field,
    "schema": _score_schema,
    "numeric": _score_numeric,
}


def score_value(output: Any, reference: Any, metric: DeterministicMetric) -> float:
    """Score one output against its reference for one deterministic metric → [0,1]."""
    return _DISPATCH[metric.comparison](output, reference, metric)


def score_item(
    input_id: str, output: Any, reference: Any, metric: DeterministicMetric
) -> ItemScore:
    """Score one input and wrap it as a deterministic ItemScore for persistence."""
    return ItemScore(
        input_id=input_id,
        metric=metric.name,
        mode="deterministic",
        value=score_value(output, reference, metric),
        rationale=None,
    )
