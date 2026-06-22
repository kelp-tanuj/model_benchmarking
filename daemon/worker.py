"""Serial benchmark worker: the link that turns a `queued` candidate into an actual run.

Loop: claim the oldest queued candidate (queued -> running) -> resolve provider/route ->
run the benchmark on every use case on disk -> mark done/failed (or pending if a key is
missing) -> post a Teams summary. ONE candidate at a time (decision #3: single serial worker),
so a scheduled drift/discovery job never overlaps a measured run.

Run:  uv run python -m daemon.worker            # continuous loop
      uv run python -m daemon.worker --once     # drain the queue once and exit
      uv run python -m daemon.worker --once --mock   # offline measured calls (still judges)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from common import repo
from common.config import settings
from common.db import connect
from common.keys import get_key
from common.leaderboard import format_cell
from daemon import teams
from daemon.orchestrator import run_benchmark, run_report

ROOT = Path(__file__).resolve().parent.parent
USECASES_DIR = ROOT / "usecases"


def _disk_use_cases() -> list[str]:
    if not USECASES_DIR.exists():
        return []
    return sorted(
        d.name for d in USECASES_DIR.iterdir()
        if d.is_dir() and (d / f"{d.name}.md").exists()
    )


def resolve_route(slug: str) -> dict | None:
    """Naive v1 provider resolution: `vendor/model` -> provider=vendor, model=model, native.

    Returns None when no key is stored for the provider (caller marks the candidate `pending`).
    Phase 5 replaces this with Foundry presence-check -> native/HF -> defer + model_aliases."""
    provider = slug.split("/")[0] if "/" in slug else slug
    model = slug.split("/", 1)[1] if "/" in slug else slug
    if not get_key(provider):
        return None
    return {"provider": provider, "model": model, "route": "native"}


def _n_reps(use_case: str) -> int:
    with connect() as c:
        cfg = repo.get_use_case_config(c, use_case)
    return (cfg or {}).get("n_reps") or settings.n_reps_default


def _summary_lines(summary: dict) -> list[str]:
    lines = [f"{m}: {format_cell(m, a.mean, a.min, a.max)}" for m, a in summary["agg"].items()]
    degraded = [m for m, v in (summary.get("drift") or {}).items() if v == "degradation"]
    if degraded:
        lines.append("⚠️ drift (degradation): " + ", ".join(degraded))
    return lines


def process_candidate(cand: dict, *, mock: bool = False) -> dict:
    slug = cand["slug"]
    route = resolve_route(slug)

    if route is None:  # blocked on a missing provider key
        provider = slug.split("/")[0] if "/" in slug else slug
        with connect() as c:
            repo.set_candidate_status(c, slug, "pending", decided_by="worker")
            repo.log(c, benchmark_id=None, run_id=None, level="warning", event="worker_blocked",
                     detail={"slug": slug, "reason": f"no key for provider '{provider}'"})
        teams.post("key_request", "chat",
                   f"Need an API key for provider '{provider}' to benchmark {slug}.",
                   card=teams.key_request_card(provider))
        return {"slug": slug, "status": "pending", "reason": "no key"}

    use_cases = _disk_use_cases()
    results: list[tuple[str, dict]] = []
    for uc in use_cases:
        try:
            summary = run_benchmark(use_case=uc, slug=slug, provider=route["provider"],
                                    model=route["model"], route=route["route"],
                                    n_reps=_n_reps(uc), mock=mock)
            try:
                run_report(summary)  # report is best-effort; a failure here must not fail the run
            except Exception:
                pass
            results.append((uc, summary))
        except Exception as exc:
            with connect() as c:
                repo.log(c, benchmark_id=None, run_id=None, level="error",
                         event="worker_run_error",
                         detail={"slug": slug, "use_case": uc, "error": str(exc)[:300]})
            results.append((uc, {"status": "failed", "use_case": uc}))

    ok = any(s.get("status") in ("done", "partial") for _, s in results)
    final = "done" if ok else "failed"
    with connect() as c:
        repo.set_candidate_status(c, slug, final, decided_by="worker")

    for uc, s in results:
        if s.get("status") in ("done", "partial"):
            teams.post("summary", "channel", f"Benchmark complete: {slug} on {uc}",
                       card=teams.summary_card(slug, uc, _summary_lines(s)))
    return {"slug": slug, "status": final,
            "results": [(uc, s.get("status")) for uc, s in results]}


def run_once(*, mock: bool = False) -> dict | None:
    """Claim + process one candidate. Returns None when the queue is empty."""
    with connect() as c:
        cand = repo.claim_queued_candidate(c)
    if not cand:
        return None
    print(f"[worker] claimed {cand['slug']} (source={cand['source']})")
    res = process_candidate(cand, mock=mock)
    print(f"[worker] {cand['slug']} -> {res['status']}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="Serial benchmark worker.")
    ap.add_argument("--once", action="store_true", help="drain the queue once and exit")
    ap.add_argument("--mock", action="store_true", help="offline measured calls (still judges)")
    args = ap.parse_args()

    if args.once:
        n = 0
        while run_once(mock=args.mock) is not None:
            n += 1
        print(f"[worker] processed {n} candidate(s)")
        return

    print(f"[worker] polling for queued candidates every {settings.worker_poll_seconds}s")
    while True:
        if run_once(mock=args.mock) is None:  # queue empty -> wait; else loop to drain
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
