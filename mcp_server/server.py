"""Per-job stdio MCP server. claude -p connects to this to run one eval rep.

Config comes from env (set by the orchestrator via the mcp-config `env` block):
  KELP_PROVIDER, KELP_MODEL, KELP_MOCK ("1" uses the offline mock caller), KELP_USECASE_ROOT.

Guardrails live here, not in the agent: the measured call does the real timed round-trip and
reads the provider key via get_key (never in the agent's context); deterministic scoring is
code; all writes are idempotent. The agent composes these tools + does semantic judging.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from common import repo
from common.db import connect
from harness.candidate_caller import MockCandidateCaller
from harness.litellm_caller import LiteLLMCandidateCaller
from harness.scorers import score_value
from harness.types import MeasuredResult
from harness.usecase import load_golden, load_usecase

mcp = FastMCP("kelp")

PROVIDER = os.environ.get("KELP_PROVIDER") or "gemini"
MODEL = os.environ.get("KELP_MODEL") or None
MOCK = os.environ.get("KELP_MOCK", "0") == "1"
ROOT = os.environ.get("KELP_USECASE_ROOT", "usecases")

_caller = None


def _golden_map(use_case: str) -> dict:
    return {r["input_id"]: r for r in load_golden(use_case, ROOT)}


def _get_caller(use_case: str):
    global _caller
    if _caller is not None:
        return _caller
    if MOCK:
        uc = load_usecase(use_case, ROOT)
        det = uc.deterministic_metrics
        canned = {}
        for rec in load_golden(use_case, ROOT):
            # mock "perfect" candidate: echo the first deterministic reference, else a stub
            out = str(rec["references"].get(det[0].name, "mock")) if det else "mock"
            canned[rec["input_id"]] = MeasuredResult(
                output=out, latency_ms=10.0, tokens_in=5, tokens_out=2, cost=0.0,
                call_breakdown=[{"step": "mock"}],
            )
        _caller = MockCandidateCaller(canned)
    else:
        _caller = LiteLLMCandidateCaller(provider=PROVIDER, model=MODEL)
    return _caller


@mcp.tool()
def get_use_case_skill(use_case: str) -> str:
    """Return the use-case skill markdown (rubric, judge_prompt, which metrics are semantic)."""
    return load_usecase(use_case, ROOT).md


@mcp.tool()
def get_golden_set(use_case: str) -> list:
    """Return validated golden records: [{input_id, input, references}]."""
    return [
        {"input_id": r["input_id"], "input": r["input"], "references": r.get("references", {})}
        for r in load_golden(use_case, ROOT)
    ]


@mcp.tool()
def measured_candidate_call(use_case: str, run_id: int, input_id: str) -> dict:
    """Run the candidate model on one input (real timed round-trip, no tools), persist the
    result, and return the measured numbers. Prompt + temperature are fixed by the skill."""
    uc = load_usecase(use_case, ROOT)
    rec = _golden_map(use_case)[input_id]
    caller = _get_caller(use_case)
    if MOCK:
        res = caller.call(input_id, {})
    else:
        req = LiteLLMCandidateCaller.build_request(
            uc.invocation["prompt_template"], rec["input"], uc.temperature
        )
        res = caller.call(input_id, req)
    with connect() as c:
        repo.write_result(
            c, run_id=run_id, use_case=use_case, input_id=input_id, raw_output=res.output,
            latency_ms=res.latency_ms, tokens_in=res.tokens_in, tokens_out=res.tokens_out,
            cost=res.cost, call_breakdown=res.call_breakdown,
        )
    return {
        "input_id": input_id, "output": res.output, "latency_ms": res.latency_ms,
        "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "cost": res.cost,
    }


@mcp.tool()
def score_deterministic(use_case: str, run_id: int, input_id: str) -> dict:
    """Code-score the deterministic metrics for one input against its reference; persist."""
    uc = load_usecase(use_case, ROOT)
    rec = _golden_map(use_case)[input_id]
    out: dict[str, float] = {}
    with connect() as c:
        stored = {r["input_id"]: r for r in repo.get_results(c, run_id)}
        output = stored.get(input_id, {}).get("raw_output")
        for dm in uc.deterministic_metrics:
            val = score_value(output, rec["references"].get(dm.name), dm)
            repo.write_item_score(
                c, run_id=run_id, input_id=input_id, use_case=use_case, metric=dm.name,
                mode="deterministic", value=val,
            )
            out[dm.name] = val
    return out


@mcp.tool()
def get_results(run_id: int) -> list:
    """Return stored candidate outputs for the run: [{input_id, output}] (for batched judging)."""
    with connect() as c:
        return [{"input_id": r["input_id"], "output": r["raw_output"]}
                for r in repo.get_results(c, run_id)]


@mcp.tool()
def write_item_scores(run_id: int, use_case: str, scores: list[dict]) -> dict:
    """Persist the agent's per-input SEMANTIC scores: [{input_id, metric, value, rationale}]."""
    n = 0
    with connect() as c:
        for s in scores:
            repo.write_item_score(
                c, run_id=run_id, input_id=s["input_id"], use_case=use_case,
                metric=s["metric"], mode="semantic", value=float(s["value"]),
                rationale=s.get("rationale"),
            )
            n += 1
    return {"written": n}


if __name__ == "__main__":
    mcp.run()
