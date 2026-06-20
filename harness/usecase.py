"""Use-case loader: parse a skill `.md` (YAML front-matter = machine-readable config; body =
human/judge prose) and load + validate its golden set.

The MD doubles as the `claude -p` skill: the agent reads the whole file (front-matter + body)
for judge instructions, while code reads the front-matter for metric specs, invocation shape,
and run config. Keeping the machine-readable parts in front-matter avoids brittle prose
parsing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness.types import DeterministicMetric

GOLDEN_REQUIRED = ("input_id", "input", "references")


@dataclass(frozen=True)
class MetricSpec:
    name: str
    mode: str  # "deterministic" | "semantic"
    comparison: str | None = None  # for deterministic
    params: dict = field(default_factory=dict)
    direction: str = "higher_better"


@dataclass(frozen=True)
class UseCase:
    id: str
    n_reps: int
    temperature: float
    invocation: dict
    metrics: tuple[MetricSpec, ...]
    judge_prompt: str
    baseline_model: str | None
    md: str  # full file contents (front-matter + body) — what claude -p reads
    root: Path

    @property
    def deterministic_metrics(self) -> list[DeterministicMetric]:
        out = []
        for m in self.metrics:
            if m.mode != "deterministic":
                continue
            out.append(
                DeterministicMetric(
                    name=m.name,
                    comparison=m.comparison or "exact",
                    fields=tuple(m.params["fields"]) if m.params.get("fields") else None,
                    json_schema=m.params.get("json_schema"),
                    tolerance=float(m.params.get("tolerance", 0.0)),
                    rel_tolerance=float(m.params.get("rel_tolerance", 0.0)),
                    normalize=bool(m.params.get("normalize", True)),
                    direction=m.direction,
                )
            )
        return out

    @property
    def semantic_metrics(self) -> list[MetricSpec]:
        return [m for m in self.metrics if m.mode == "semantic"]


def _split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("skill MD must start with a YAML front-matter block (---)")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("malformed front-matter: expected opening and closing ---")
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def load_usecase(usecase_id: str, root: str | Path = "usecases") -> UseCase:
    base = Path(root) / usecase_id
    md_path = base / f"{usecase_id}.md"
    text = md_path.read_text()
    meta, _body = _split_front_matter(text)

    metrics = tuple(
        MetricSpec(
            name=m["name"],
            mode=m["mode"],
            comparison=m.get("comparison"),
            params=m.get("params", {}),
            direction=m.get("direction", "higher_better"),
        )
        for m in meta.get("metrics", [])
    )
    if not metrics:
        raise ValueError(f"use case {usecase_id!r} defines no metrics")

    return UseCase(
        id=meta.get("id", usecase_id),
        n_reps=int(meta.get("n_reps", 3)),
        temperature=float(meta.get("temperature", 0.0)),
        invocation=meta.get("invocation", {"shape": "single_call"}),
        metrics=metrics,
        judge_prompt=meta.get("judge_prompt", ""),
        baseline_model=meta.get("baseline_model"),
        md=text,
        root=base,
    )


def load_golden(usecase_id: str, root: str | Path = "usecases") -> list[dict]:
    """Load + validate golden.jsonl. Fails fast on malformed/duplicate records."""
    path = Path(root) / usecase_id / "golden.jsonl"
    records: list[dict] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from e
        for key in GOLDEN_REQUIRED:
            if key not in rec:
                raise ValueError(f"{path}:{lineno}: missing required key {key!r}")
        iid = rec["input_id"]
        if iid in seen:
            raise ValueError(f"{path}:{lineno}: duplicate input_id {iid!r}")
        seen.add(iid)
        records.append(rec)
    if not records:
        raise ValueError(f"{path}: golden set is empty")
    return records


def validate(usecase_id: str, root: str | Path = "usecases") -> tuple[UseCase, list[dict]]:
    """Load both halves and cross-check that deterministic metrics have references."""
    uc = load_usecase(usecase_id, root)
    golden = load_golden(usecase_id, root)
    det_names = [m.name for m in uc.deterministic_metrics]
    for rec in golden:
        refs = rec.get("references", {})
        for name in det_names:
            if name not in refs:
                raise ValueError(
                    f"input {rec['input_id']!r} is missing reference for deterministic "
                    f"metric {name!r}"
                )
    return uc, golden
