"""Drift re-run (phase 2): re-benchmark a use case's configured baseline model and flag
degradation vs its baseline band.

Reuses the orchestrator's run_benchmark (is_baseline=False); the drift verdict it returns
already applies the direction-aware "mean outside band, degradation only" rule. Alerts are
logged + printed for now; Teams alerting arrives in phase 3.
"""

from __future__ import annotations

import argparse

from common import repo
from common.config import settings
from common.db import connect
from daemon.orchestrator import run_benchmark


def _resolve_baseline_model(use_case: str) -> tuple[str, int] | None:
    """Return (model_slug, n_reps) from admin config, falling back to the baseline row."""
    with connect() as c:
        cfg = repo.get_use_case_config(c, use_case)
        if cfg and cfg.get("baseline_model"):
            return cfg["baseline_model"], cfg.get("n_reps") or settings.n_reps_default
        baseline = repo.get_baseline(c, use_case)
    if not baseline:
        return None
    model = next(iter(baseline.values())).get("model")
    return (model, settings.n_reps_default) if model else None


def run_drift(use_case: str, reps: int | None = None, mock: bool = False) -> dict | None:
    resolved = _resolve_baseline_model(use_case)
    if not resolved:
        print(f"[drift] no baseline configured for {use_case!r}; skipping")
        return None
    slug, default_reps = resolved
    if "/" not in slug:
        print(f"[drift] baseline_model {slug!r} for {use_case!r} must be 'provider/model'; skipping")
        return None
    provider, _, model = slug.partition("/")

    summary = run_benchmark(
        use_case=use_case, slug=slug, provider=provider, model=model,
        route="native", n_reps=reps or default_reps, mock=mock,
        is_baseline=False, is_drift=True,
    )
    degradations = {m: d for m, d in summary["drift"].items() if d == "degradation"}
    with connect() as c:
        repo.log(
            c, benchmark_id=summary["benchmark_id"], run_id=None,
            level="warning" if degradations else "info",
            event="drift_check", detail={"drift": summary["drift"]},
        )
    if degradations:
        print(f"[drift] ⚠️ DEGRADATION for {use_case}: {degradations}  (benchmark {summary['benchmark_id']})")
    else:
        print(f"[drift] ✓ {use_case} within band: {summary['drift'] or 'no baseline metrics'}")
    return summary


def use_cases_with_baseline() -> list[str]:
    with connect() as c:
        rows = c.execute("SELECT DISTINCT use_case FROM baselines ORDER BY use_case").fetchall()
    return [r["use_case"] for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-run baseline model(s) and check drift.")
    ap.add_argument("--use-case", default=None, help="omit to run all use cases with a baseline")
    ap.add_argument("--reps", type=int, default=None)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    targets = [args.use_case] if args.use_case else use_cases_with_baseline()
    if not targets:
        print("[drift] no use cases with a baseline")
        return
    for uc in targets:
        try:
            run_drift(uc, reps=args.reps, mock=args.mock)
        except Exception as exc:  # one bad use case must not abort the sweep
            print(f"[drift] ERROR for {uc}: {exc}")


if __name__ == "__main__":
    main()
