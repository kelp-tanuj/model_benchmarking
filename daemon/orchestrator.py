"""Milestone-#1 orchestrator.

Per decision #6, a `claude -p` session orchestrates each rep via the MCP code tools; Python
owns the deterministic parts (aggregation, drift) and the per-rep loop. Web tools are
explicitly disallowed on every claude invocation (the user has no web-search quota).

Flow: create benchmark → for each rep { create run → claude -p rep session → code computes
scores_per_run from item_scores } → aggregate across reps → drift vs baseline → (optionally
set baseline) → claude -p writes the report → save it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from common import repo
from common.config import settings
from common.db import connect
from harness.aggregate import aggregate_benchmark, default_metric_rollup, per_run_means
from harness.drift import drift_check
from harness.types import Aggregate, ItemScore
from harness.usecase import validate

ROOT = Path(__file__).resolve().parent.parent
TOOLS = [
    "get_use_case_skill", "get_golden_set", "measured_candidate_call",
    "score_deterministic", "get_results", "write_item_scores",
]
ALLOWED = ",".join(f"mcp__kelp__{t}" for t in TOOLS)
NO_WEB = ["--disallowedTools", "WebSearch,WebFetch"]

REP_PROMPT = """You are running ONE evaluation repetition for use case '{use_case}', run_id={run_id}.
Use ONLY the provided MCP tools. Do NOT use web search or any other tool.

1. Call get_use_case_skill('{use_case}') and read the rubric, the judge_prompt, and which
   metrics are tagged 'semantic'.
2. Call get_golden_set('{use_case}') to get the inputs (each has input_id, input, references).
3. For EACH input_id, in order:
   a. measured_candidate_call('{use_case}', {run_id}, input_id)
   b. score_deterministic('{use_case}', {run_id}, input_id)
4. Then perform the SEMANTIC judging exactly as the skill's judge_prompt instructs, for every
   semantic metric, comparing each candidate output to its reference. Call get_results({run_id})
   if you need the outputs again.
5. Write ALL semantic scores in ONE call:
   write_item_scores({run_id}, '{use_case}',
     [{{"input_id": "...", "metric": "...", "value": <float 0..1>, "rationale": "..."}}, ...]).
6. Reply with ONLY a compact JSON object: {{"inputs_done": <int>, "semantic_written": <int>}}.
"""

REPORT_PROMPT = """Write a concise markdown benchmark report. Do NOT use any tools.

Use case: {use_case}
Model: {slug}    Provider/route: {provider}/{route}    Reps: {n_reps}    Judge: {judge}

Aggregated quality + default metrics (mean and min–max range across reps):
{scores_table}

Drift vs baseline: {drift}

Cover, briefly: headline quality, latency/cost trade-off, and a one-line recommendation.
Note that the judge is uncalibrated (stability gauge, not accuracy). Output ONLY markdown.
"""


def _mcp_config(provider: str | None, model: str | None, mock: bool) -> str:
    cfg = {
        "mcpServers": {
            "kelp": {
                "command": "uv",
                "args": ["run", "--directory", str(ROOT), "python", "-m", "mcp_server.server"],
                "env": {
                    "KELP_PROVIDER": provider or "",
                    "KELP_MODEL": model or "",
                    "KELP_MOCK": "1" if mock else "0",
                },
            }
        }
    }
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=str(ROOT))
    json.dump(cfg, f)
    f.close()
    return f.name


def _claude(prompt: str, *, mcp_config: str | None, allowed: str | None, max_turns: int,
            timeout: int) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", settings.judge_model,
           "--max-turns", str(max_turns), *NO_WEB]
    if mcp_config:
        cmd += ["--mcp-config", mcp_config]
    if allowed:
        cmd += ["--allowedTools", allowed]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                          env=dict(os.environ), timeout=timeout)
    if not proc.stdout.strip():
        return {"is_error": True, "result": None, "stderr": proc.stderr[-800:]}
    return json.loads(proc.stdout)


def run_rep(use_case: str, run_id: int, provider: str | None, model: str | None,
            mock: bool) -> dict:
    cfg = _mcp_config(provider, model, mock)
    try:
        return _claude(REP_PROMPT.format(use_case=use_case, run_id=run_id),
                       mcp_config=cfg, allowed=ALLOWED, max_turns=60, timeout=900)
    finally:
        try:
            os.unlink(cfg)
        except OSError:
            pass


def run_benchmark(*, use_case: str, slug: str, provider: str | None, model: str | None,
                  route: str | None, n_reps: int, mock: bool = False,
                  is_baseline: bool = False) -> dict:
    uc, _golden = validate(use_case)
    directions = {m.name: m.direction for m in uc.metrics}
    # default metrics are lower-is-better for cost/latency
    directions.update({"latency_ms": "lower_better", "cost": "lower_better"})
    judge = settings.judge_model

    with connect() as c:
        bid = repo.create_benchmark(
            c, slug=slug, use_case=use_case, route=route, provider=provider,
            judge_model=judge, judge_version=judge, n_reps=n_reps, is_baseline=is_baseline,
        )
        repo.log(c, benchmark_id=bid, run_id=None, level="info", event="benchmark_start",
                 detail={"slug": slug, "n_reps": n_reps, "mock": mock})

    per_rep_means: list[dict] = []
    for rep in range(n_reps):
        with connect() as c:
            rid = repo.upsert_run(c, bid, rep)
        result = run_rep(use_case, rid, provider, model, mock)
        with connect() as c:
            items = repo.get_item_scores(c, rid)
            means = per_run_means([
                ItemScore(input_id=i["input_id"], metric=i["metric"], mode=i["mode"],
                          value=i["value"], rationale=i.get("rationale"))
                for i in items
            ])
            means.update(default_metric_rollup(repo.get_results(c, rid)))  # latency/tokens/cost
            for metric, val in means.items():
                repo.upsert_scores_per_run(c, run_id=rid, use_case=use_case, metric=metric,
                                           value=val)
            status = "done" if result.get("is_error") is not True else "failed"
            repo.finish_run(c, rid, status, transcript=result)
            repo.log(c, benchmark_id=bid, run_id=rid, level="info", event="rep_done",
                     detail={"means": means, "agent": result.get("result")})
        per_rep_means.append(means)

    agg = aggregate_benchmark(per_rep_means)
    drift: dict[str, str] = {}
    with connect() as c:
        for metric, a in agg.items():
            repo.upsert_score(c, benchmark_id=bid, use_case=use_case, metric=metric,
                              mean=a.mean, min=a.min, max=a.max)
        baseline = repo.get_baseline(c, use_case)
        for metric, a in agg.items():
            if metric in baseline:
                b = baseline[metric]
                bd = Aggregate(mean=b["mean"], min=b["min"], max=b["max"], n=0)
                drift[metric] = drift_check(
                    a.mean, bd, directions.get(metric, "higher_better")
                ).direction
        if is_baseline:
            for metric, a in agg.items():
                repo.upsert_baseline(c, use_case=use_case, metric=metric, mean=a.mean,
                                     min=a.min, max=a.max, model=slug, benchmark_id=bid,
                                     judge_model=judge, judge_version=judge)
        repo.finish_benchmark(c, bid, "done")

    return {"benchmark_id": bid, "agg": agg, "drift": drift, "use_case": use_case,
            "slug": slug, "provider": provider, "route": route, "n_reps": n_reps}


def run_report(summary: dict) -> Path:
    agg = summary["agg"]
    table = "\n".join(
        f"- {m}: mean={a.mean:.4f} range=[{a.min:.4f}, {a.max:.4f}]" for m, a in agg.items()
    )
    prompt = REPORT_PROMPT.format(
        use_case=summary["use_case"], slug=summary["slug"], provider=summary["provider"],
        route=summary["route"], n_reps=summary["n_reps"], judge=settings.judge_model,
        scores_table=table, drift=summary["drift"] or "no baseline yet",
    )
    res = _claude(prompt, mcp_config=None, allowed=None, max_turns=3, timeout=300)
    md = (res.get("result") or "(report generation failed)").strip()
    if md.startswith("```"):  # strip a wrapping code fence if the model added one
        lines = md.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        md = "\n".join(lines).strip()
    out_dir = ROOT / "reports" / summary["use_case"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{summary['benchmark_id']}.md"
    path.write_text(md)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a Kelp benchmark (milestone #1).")
    ap.add_argument("--use-case", required=True)
    ap.add_argument("--slug", required=True, help="candidate model slug, e.g. gemini/gemini-2.5-flash-lite")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--route", default="native")
    ap.add_argument("--reps", type=int, default=settings.n_reps_default)
    ap.add_argument("--mock", action="store_true", help="use the offline mock caller")
    ap.add_argument("--baseline", action="store_true", help="record this run as the baseline")
    ap.add_argument("--report", action="store_true", help="also generate the markdown report")
    args = ap.parse_args()

    summary = run_benchmark(
        use_case=args.use_case, slug=args.slug, provider=args.provider, model=args.model,
        route=args.route, n_reps=args.reps, mock=args.mock, is_baseline=args.baseline,
    )
    print(f"benchmark_id={summary['benchmark_id']}")
    for m, a in summary["agg"].items():
        print(f"  {m}: mean={a.mean:.4f} range=[{a.min:.4f}, {a.max:.4f}]")
    if summary["drift"]:
        print(f"  drift: {summary['drift']}")
    if args.report:
        path = run_report(summary)
        print(f"report: {path}")


if __name__ == "__main__":
    main()
