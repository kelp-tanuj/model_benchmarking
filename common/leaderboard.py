"""Leaderboard data assembly — pure (no Streamlit), so it's testable.

Builds one row per benchmark (model tested) for a use case, each metric formatted as
mean [min–max] across reps, with quality metrics first and the default harness metrics
(latency/tokens/cost) last.
"""

from __future__ import annotations

from common import repo
from common.db import connect

DEFAULT_METRICS = ["latency_ms", "tokens_in", "tokens_out", "cost"]


def format_cell(metric: str, mean: float, mn: float, mx: float) -> str:
    flat = abs(mx - mn) < 1e-9
    if metric == "latency_ms":
        return f"{mean:.0f} ms" + ("" if flat else f" [{mn:.0f}–{mx:.0f}]")
    if metric == "cost":
        if mean == 0:
            return "$0"
        return f"${mean:.2e}" + ("" if flat else f" [{mn:.2e}–{mx:.2e}]")
    if metric in ("tokens_in", "tokens_out"):
        return f"{mean:.0f}"
    return f"{mean:.3f}" + ("" if flat else f" [{mn:.3f}–{mx:.3f}]")


def build_rows(use_case: str) -> dict:
    with connect() as c:
        benches = repo.get_benchmarks(c, use_case)
        scores = repo.get_scores_for_use_case(c, use_case)

    by_bid: dict[int, dict[str, tuple]] = {}
    seen: list[str] = []
    for s in scores:
        by_bid.setdefault(s["benchmark_id"], {})[s["metric"]] = (
            float(s["mean"]), float(s["min"]), float(s["max"])
        )
        if s["metric"] not in seen:
            seen.append(s["metric"])

    quality = sorted(m for m in seen if m not in DEFAULT_METRICS)
    metrics = quality + [m for m in DEFAULT_METRICS if m in seen]

    rows = []
    for b in benches:
        sc = by_bid.get(b["benchmark_id"], {})
        rows.append({
            "benchmark_id": b["benchmark_id"],
            "model": b["slug"],
            "is_baseline": b["is_baseline"],
            "reps": b["n_reps"],
            "judge_model": b["judge_model"],
            "cells": {m: (format_cell(m, *sc[m]) if m in sc else "—") for m in metrics},
        })
    return {"metrics": metrics, "rows": rows}
