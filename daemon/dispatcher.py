"""Free-text intent dispatcher (the cognitive bit of the Teams flow).

A `claude -p` call CLASSIFIES the message into a structured intent (no tools — pure text→JSON);
CODE (in the consumer) then reconciles the model against the OpenRouter catalog, drives the
cards, and enforces confirm-before-spend. The classifier runs with a strict NO-TOOLS posture
(allowlist, not denylist) and a scrubbed env, so untrusted Teams text can do nothing but
produce a JSON intent that code then validates.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from common.config import settings

ROOT = Path(__file__).resolve().parent.parent
EMPTY_MCP = str(ROOT / "daemon" / "empty_mcp.json")  # {"mcpServers": {}} — strict needs a companion
DENY_TOOLS = ("WebSearch,WebFetch,Bash,Read,Write,Edit,MultiEdit,Glob,Grep,"
              "NotebookEdit,Task,LS")
# App secrets that must never reach the classifier subprocess (defense-in-depth; the agent
# also has no tools, so it cannot read its env regardless).
_SECRET_ENV = ("DATABASE_URL", "KEY_INGEST_SECRET", "TEAMS_POST_FLOW_URL")

PARSE_PROMPT = """Parse this Microsoft Teams message into a model-benchmark intent.
Do NOT use any tools. Do NOT search the web.

Message: {text}

Return ONLY a JSON object (no prose, no code fence):
{{"action": "benchmark" | "unknown",
  "model_query": "<the model name/phrase the user wants tested, or null>",
  "use_cases": ["<use-case id>", ...] or null}}

Use "benchmark" only if the user is clearly asking to test/benchmark/evaluate a model.
Otherwise use "unknown".
"""


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


def as_use_case_list(value) -> list[str]:
    """Normalize a use_cases value from any ingress to a clean list of ids.

    Adaptive-Card multi-select ChoiceSets return a comma-joined STRING, and the classifier
    (untrusted output) may return a string instead of an array — both collapse here.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        return []
    return [str(p).strip() for p in parts if str(p).strip()]


def _coerce_intent(intent) -> dict:
    """Validate/normalize the untrusted classifier output into a fixed, safe shape."""
    if not isinstance(intent, dict):
        return {"action": "unknown", "model_query": None, "use_cases": None}
    action = intent.get("action")
    if action not in ("benchmark", "unknown"):
        action = "unknown"
    mq = intent.get("model_query")
    if not isinstance(mq, str) or not mq.strip():
        mq = None
    ucs = as_use_case_list(intent.get("use_cases")) or None
    return {"action": action, "model_query": mq, "use_cases": ucs}


def _dispatch_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}


def parse_request(text: str) -> dict:
    cmd = ["claude", "-p", PARSE_PROMPT.format(text=text), "--output-format", "json",
           "--model", settings.judge_model, "--max-turns", "1",
           "--strict-mcp-config", "--mcp-config", EMPTY_MCP,  # no MCP servers load
           "--tools", "",                                      # allowlist: no built-in tools
           "--disallowedTools", DENY_TOOLS]                    # belt-and-suspenders
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                              env=_dispatch_env(), timeout=120)
    except Exception as exc:
        print(f"[dispatcher] claude invocation failed: {type(exc).__name__}")
        return {"action": "unknown", "model_query": None, "use_cases": None}
    if proc.returncode != 0:
        print(f"[dispatcher] claude exited {proc.returncode}: {(proc.stderr or '')[-300:]}")
        return {"action": "unknown", "model_query": None, "use_cases": None}
    try:
        result = json.loads(proc.stdout)["result"]
        intent = json.loads(_strip_fence(result))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"[dispatcher] unparseable classifier output ({type(exc).__name__})")
        return {"action": "unknown", "model_query": None, "use_cases": None}
    return _coerce_intent(intent)
