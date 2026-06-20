"""User-facing Streamlit app — read-only leaderboards + reports (phase 2).

Run:  uv run streamlit run apps/user/app.py
Reads scores/benchmarks/baselines from Neon; never writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable when Streamlit runs this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from common import repo
from common.db import connect
from common.leaderboard import build_rows

st.set_page_config(page_title="Kelp Leaderboards", layout="wide")
st.title("Kelp — Model Benchmark Leaderboards")


@st.cache_data(ttl=30)
def _use_cases() -> list[str]:
    with connect() as c:
        return repo.list_use_cases(c)


@st.cache_data(ttl=30)
def _rows(use_case: str) -> dict:
    return build_rows(use_case)


use_cases = _use_cases()
if not use_cases:
    st.info("No completed benchmarks yet. Run one with `python -m daemon.orchestrator`.")
    st.stop()

use_case = st.selectbox("Use case", use_cases)
data = _rows(use_case)

st.subheader(f"Leaderboard — {use_case}")
st.caption(
    "Each metric: **mean [min–max]** across reps. ⭐ marks the baseline. "
    "Judge is uncalibrated — treat quality scores as a stability gauge, not absolute accuracy."
)

if not data["rows"]:
    st.info("No scored benchmarks for this use case yet.")
else:
    table = []
    baseline_idx = []
    for i, r in enumerate(data["rows"]):
        label = f"⭐ {r['model']}" if r["is_baseline"] else r["model"]
        if r["is_baseline"]:
            baseline_idx.append(i)
        table.append({"model": label, "reps": r["reps"], **r["cells"]})
    df = pd.DataFrame(table)

    def _highlight(row):
        return [
            "background-color: #fff3cd" if row.name in baseline_idx else "" for _ in row
        ]

    st.dataframe(df.style.apply(_highlight, axis=1), use_container_width=True, hide_index=True)

st.subheader("Reports")
rep_dir = Path(__file__).resolve().parents[2] / "reports" / use_case
files = sorted(rep_dir.glob("*.md"), reverse=True) if rep_dir.exists() else []
if files:
    choice = st.selectbox("Report", [f.name for f in files])
    st.markdown((rep_dir / choice).read_text())
else:
    st.caption("No reports yet for this use case.")
