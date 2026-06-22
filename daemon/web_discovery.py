"""Web discovery radar: a `claude -p` workflow that uses WebSearch + WebFetch to find newly
announced LLMs across AI news/blogs, HuggingFace, Reddit, and X (best-effort), and records them
(via the isolated `kelp_disc` MCP server) as candidates for the human Benchmark/Skip gate.

This is the ONLY web-enabled `claude -p` invocation. It is a SEPARATE builder from
`orchestrator._claude` (which stays no-web) and pins a SEPARATE MCP server (`kelp_disc`) so the
web agent can never reach the key-bearing eval tools. The eval/judge/report/dispatcher no-web
hardening is untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from common import repo
from common.config import settings
from common.db import connect
from daemon import teams

ROOT = Path(__file__).resolve().parent.parent

# Web tools are ALLOWED here (the whole point); fs/shell still denied.
DISC_DENY_TOOLS = "Bash,Read,Write,Edit,MultiEdit,Glob,Grep,NotebookEdit,Task,LS"
DISC_TOOLS = ["lookup_known_models", "record_discovered_model", "discovery_budget"]
DISC_ALLOW = ",".join(["WebSearch", "WebFetch"] + [f"mcp__kelp_disc__{t}" for t in DISC_TOOLS])

_SECRET_ENV = ("DATABASE_URL", "KEY_INGEST_SECRET", "TEAMS_POST_FLOW_URL", "TEAMS_CARD_FLOW_URL")
_SECRET_RE = re.compile(
    r"(AIza[0-9A-Za-z\-_]{20,}|sk-[A-Za-z0-9\-_]{16,}|postgres(?:ql)?://[^\s\"']+)"
)

DISCOVERY_PROMPT = """You are Kelp's model-discovery scout. Find large language models ANNOUNCED
OR RELEASED in roughly the last {window_days} days that are NOT already in our catalog.
Use WebSearch and WebFetch.

HARD BUDGET: record AT MOST {target} new models. Stay under {max_turns} turns. Call
discovery_budget() periodically and STOP when remaining == 0 or you run out of fresh leads.

Sources to scan (some are best-effort):
  1. AI news / blogs + vendor release pages (OpenAI/Anthropic/Google/Mistral/DeepSeek/Qwen/etc.) —
     most reliable via WebFetch.
  2. HuggingFace models (recently created / trending text-generation models) — fetchable.
  3. Reddit r/LocalLLaMA (use old.reddit.com or .json endpoints) — public, fetchable.
  4. X/Twitter — BEST EFFORT ONLY (login-walled): rely on WebSearch snippets, don't expect full threads.

For EACH promising model:
  a. Call lookup_known_models(name) FIRST. If it returns a match, SKIP it (don't spend turns
     re-researching a model we already track).
  b. Otherwise resolve: canonical_name, provider, approximate cost, performance highlights,
     unique attributes, and source URL(s).
  c. Call record_discovered_model(...). Partial info is fine — pass null for fields you couldn't
     confirm. NEVER fabricate costs or benchmark numbers; if unknown, leave them null.

Only TEXT-generation LLMs relevant for benchmarking. Skip image/audio/video-only models,
embeddings, rerankers, speech models, and tiny (<~1B) toys.

When done, reply with ONLY this JSON (no prose, no fence):
{{"recorded": <int>, "skipped_known": <int>, "notes": "<one line>"}}
"""


def _scrub(obj):
    return json.loads(_SECRET_RE.sub("***REDACTED***", json.dumps(obj)))


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def _disc_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}


def _mcp_config(target: int) -> str:
    cfg = {
        "mcpServers": {
            "kelp_disc": {
                "command": "uv",
                "args": ["run", "--directory", str(ROOT), "python", "-m",
                         "mcp_server.discovery_server"],
                "env": {"KELP_DISC_TARGET": str(target)},
            }
        }
    }
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(cfg, f)
    f.close()
    return f.name


def build_web_cmd(prompt: str, mcp_config: str, *, model: str, max_turns: int) -> list[str]:
    """Pure command builder (unit-tested for the isolation invariant)."""
    return [
        "claude", "-p", prompt, "--output-format", "json", "--model", model,
        "--max-turns", str(max_turns),
        "--strict-mcp-config", "--mcp-config", mcp_config,
        "--allowedTools", DISC_ALLOW,
        "--disallowedTools", DISC_DENY_TOOLS,
    ]


def _run_web_claude(prompt: str, *, target: int, model: str, max_turns: int, timeout: int) -> dict:
    cfg = _mcp_config(target)
    cmd = build_web_cmd(prompt, cfg, model=model, max_turns=max_turns)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                              env=_disc_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"is_error": True, "result": None, "stderr": "timeout"}
    finally:
        try:
            os.unlink(cfg)
        except OSError:
            pass
    if not proc.stdout.strip():
        return {"is_error": True, "result": None, "stderr": (proc.stderr or "")[-800:]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": None, "stderr": (proc.stdout or "")[-800:]}


def _parse_summary(result) -> dict:
    if not isinstance(result, str):
        return {}
    try:
        obj = json.loads(_strip_fence(result))
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _web_candidate_slugs() -> set[str]:
    with connect() as c:
        return {x["slug"] for x in repo.list_candidates(c) if x["source"] == "web"}


def run_web_discovery(*, target: int | None = None, max_turns: int | None = None,
                      post_cards: bool = True, runner=None) -> dict:
    """Run the web-research agent (it records candidates via MCP), then summarize + notify.

    `runner(prompt) -> claude-result-dict` is injectable for offline tests."""
    target = target or settings.web_discovery_target
    max_turns = max_turns or settings.web_discovery_max_turns
    prompt = DISCOVERY_PROMPT.format(
        window_days=settings.web_discovery_window_days, target=target, max_turns=max_turns)

    before = _web_candidate_slugs()
    if runner is not None:
        res = runner(prompt)
    else:
        res = _run_web_claude(prompt, target=target, model=settings.web_discovery_model,
                              max_turns=max_turns, timeout=settings.web_discovery_timeout)
    after = _web_candidate_slugs()
    new_slugs = sorted(after - before)
    summary = _parse_summary(res.get("result"))

    with connect() as c:
        repo.log(c, benchmark_id=None, run_id=None,
                 level="error" if res.get("is_error") else "info", event="web_discovery",
                 detail={"recorded": len(new_slugs), "new_slugs": new_slugs,
                         "agent_summary": summary,
                         "error": res.get("stderr") if res.get("is_error") else None})

    if post_cards and new_slugs:
        teams.post("web_discovery", "channel",
                   f"🔎 Web discovery: {len(new_slugs)} new candidate model(s) — review in the "
                   f"admin console.",
                   card=teams.alert_card("New models discovered (web)",
                                         [f"`{s}`" for s in new_slugs[:15]]))

    return {"new_slugs": new_slugs, "agent_summary": summary, "is_error": bool(res.get("is_error"))}


def main() -> None:
    ap = argparse.ArgumentParser(description="Web-research discovery radar (claude -p).")
    ap.add_argument("--target", type=int, default=None, help="max models to record this run")
    ap.add_argument("--max-turns", type=int, default=None)
    ap.add_argument("--no-cards", action="store_true", help="don't post the Teams summary")
    args = ap.parse_args()
    res = run_web_discovery(target=args.target, max_turns=args.max_turns,
                            post_cards=not args.no_cards)
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
