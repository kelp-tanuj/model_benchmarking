"""Free-text intent dispatcher (the cognitive bit of the Teams flow).

A `claude -p` call CLASSIFIES the message into a structured intent (no tools — pure text→JSON);
CODE (in the consumer) then reconciles the model against the OpenRouter catalog, drives the
cards, and enforces confirm-before-spend. The agent has no tools, so untrusted Teams text can
do nothing but produce a JSON intent that code validates.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from common.config import settings

ROOT = Path(__file__).resolve().parent.parent
DENY_TOOLS = ("WebSearch,WebFetch,Bash,Read,Write,Edit,MultiEdit,Glob,Grep,"
              "NotebookEdit,Task,LS")

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


def parse_request(text: str) -> dict:
    cmd = ["claude", "-p", PARSE_PROMPT.format(text=text), "--output-format", "json",
           "--model", settings.judge_model, "--max-turns", "1",
           "--disallowedTools", DENY_TOOLS]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                              env=dict(os.environ), timeout=120)
        result = json.loads(proc.stdout)["result"]
        intent = json.loads(_strip_fence(result))
    except Exception as exc:
        return {"action": "unknown", "model_query": None, "use_cases": None, "error": str(exc)}
    # Normalize / validate the shape (untrusted output).
    if intent.get("action") not in ("benchmark", "unknown"):
        intent["action"] = "unknown"
    intent.setdefault("model_query", None)
    intent.setdefault("use_cases", None)
    return intent
