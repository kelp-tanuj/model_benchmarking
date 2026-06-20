"""Repository layer — all SQL for the eval loop, drift, and leaderboard.

Functions take an open psycopg connection (caller manages the transaction via
`common.db.connect()`), so a rep's writes commit/rollback atomically. Result/score writes
are idempotent on their natural key (ON CONFLICT) so an interrupted rep resumes cleanly.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json


# --- Benchmarks / runs ---------------------------------------------------------------

def create_benchmark(
    conn: psycopg.Connection,
    *,
    slug: str,
    use_case: str,
    route: str | None,
    provider: str | None,
    judge_model: str | None,
    judge_version: str | None,
    n_reps: int,
    is_baseline: bool = False,
) -> int:
    row = conn.execute(
        """
        INSERT INTO benchmarks
            (slug, use_case, route, provider, judge_model, judge_version, n_reps,
             is_baseline, started_at, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now(), 'running')
        RETURNING benchmark_id
        """,
        (slug, use_case, route, provider, judge_model, judge_version, n_reps, is_baseline),
    ).fetchone()
    return row["benchmark_id"]


def finish_benchmark(conn: psycopg.Connection, benchmark_id: int, status: str) -> None:
    conn.execute(
        "UPDATE benchmarks SET status=%s, finished_at=now() WHERE benchmark_id=%s",
        (status, benchmark_id),
    )


def upsert_run(conn: psycopg.Connection, benchmark_id: int, rep_index: int) -> int:
    row = conn.execute(
        """
        INSERT INTO runs (benchmark_id, rep_index, started_at, status)
        VALUES (%s,%s, now(), 'running')
        ON CONFLICT (benchmark_id, rep_index)
        DO UPDATE SET status='running', started_at=COALESCE(runs.started_at, now())
        RETURNING run_id
        """,
        (benchmark_id, rep_index),
    ).fetchone()
    return row["run_id"]


def finish_run(
    conn: psycopg.Connection, run_id: int, status: str, transcript: Any | None = None
) -> None:
    conn.execute(
        "UPDATE runs SET status=%s, finished_at=now(), transcript=%s WHERE run_id=%s",
        (status, Json(transcript) if transcript is not None else None, run_id),
    )


# --- Per-input results + scores (idempotent) -----------------------------------------

def write_result(
    conn: psycopg.Connection,
    *,
    run_id: int,
    use_case: str,
    input_id: str,
    raw_output: str | None,
    latency_ms: float | None,
    tokens_in: int | None,
    tokens_out: int | None,
    cost: float | None,
    call_breakdown: Any | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO results
            (run_id, use_case, input_id, raw_output, latency_ms, tokens_in, tokens_out,
             cost, call_breakdown)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (run_id, input_id) DO UPDATE SET
            raw_output=EXCLUDED.raw_output, latency_ms=EXCLUDED.latency_ms,
            tokens_in=EXCLUDED.tokens_in, tokens_out=EXCLUDED.tokens_out,
            cost=EXCLUDED.cost, call_breakdown=EXCLUDED.call_breakdown
        """,
        (run_id, use_case, input_id, raw_output, latency_ms, tokens_in, tokens_out,
         cost, Json(call_breakdown) if call_breakdown is not None else None),
    )


def write_item_score(
    conn: psycopg.Connection,
    *,
    run_id: int,
    input_id: str,
    use_case: str,
    metric: str,
    mode: str,
    value: float,
    rationale: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO item_scores (run_id, input_id, use_case, metric, mode, value, rationale)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (run_id, input_id, metric) DO UPDATE SET
            mode=EXCLUDED.mode, value=EXCLUDED.value, rationale=EXCLUDED.rationale
        """,
        (run_id, input_id, use_case, metric, mode, value, rationale),
    )


def upsert_scores_per_run(
    conn: psycopg.Connection, *, run_id: int, use_case: str, metric: str, value: float
) -> None:
    conn.execute(
        """
        INSERT INTO scores_per_run (run_id, use_case, metric, value)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (run_id, metric) DO UPDATE SET value=EXCLUDED.value, use_case=EXCLUDED.use_case
        """,
        (run_id, use_case, metric, value),
    )


def upsert_score(
    conn: psycopg.Connection,
    *,
    benchmark_id: int,
    use_case: str,
    metric: str,
    mean: float,
    min: float,
    max: float,
) -> None:
    conn.execute(
        """
        INSERT INTO scores (benchmark_id, use_case, metric, mean, min, max)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (benchmark_id, metric) DO UPDATE SET
            mean=EXCLUDED.mean, min=EXCLUDED.min, max=EXCLUDED.max, use_case=EXCLUDED.use_case
        """,
        (benchmark_id, use_case, metric, mean, min, max),
    )


# --- Baselines + config --------------------------------------------------------------

def upsert_baseline(
    conn: psycopg.Connection,
    *,
    use_case: str,
    metric: str,
    mean: float,
    min: float,
    max: float,
    model: str | None,
    benchmark_id: int | None,
    judge_model: str | None,
    judge_version: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO baselines
            (use_case, metric, mean, min, max, model, benchmark_id, judge_model,
             judge_version, set_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
        ON CONFLICT (use_case, metric) DO UPDATE SET
            mean=EXCLUDED.mean, min=EXCLUDED.min, max=EXCLUDED.max, model=EXCLUDED.model,
            benchmark_id=EXCLUDED.benchmark_id, judge_model=EXCLUDED.judge_model,
            judge_version=EXCLUDED.judge_version, set_at=now()
        """,
        (use_case, metric, mean, min, max, model, benchmark_id, judge_model, judge_version),
    )


def get_baseline(conn: psycopg.Connection, use_case: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT metric, mean, min, max, model, judge_model, judge_version "
        "FROM baselines WHERE use_case=%s",
        (use_case,),
    ).fetchall()
    return {r["metric"]: dict(r) for r in rows}


def get_use_case_config(conn: psycopg.Connection, use_case: str) -> dict | None:
    return conn.execute(
        "SELECT use_case, baseline_model, n_reps, temperature FROM use_case_config "
        "WHERE use_case=%s",
        (use_case,),
    ).fetchone()


def set_use_case_config(
    conn: psycopg.Connection,
    *,
    use_case: str,
    baseline_model: str | None,
    n_reps: int,
    temperature: float | None,
) -> None:
    conn.execute(
        """
        INSERT INTO use_case_config (use_case, baseline_model, n_reps, temperature, updated_at)
        VALUES (%s,%s,%s,%s, now())
        ON CONFLICT (use_case) DO UPDATE SET
            baseline_model=EXCLUDED.baseline_model, n_reps=EXCLUDED.n_reps,
            temperature=EXCLUDED.temperature, updated_at=now()
        """,
        (use_case, baseline_model, n_reps, temperature),
    )


# --- Reads for aggregation / leaderboard / logs --------------------------------------

def get_item_scores(conn: psycopg.Connection, run_id: int) -> list[dict]:
    return conn.execute(
        "SELECT input_id, metric, mode, value, rationale FROM item_scores WHERE run_id=%s",
        (run_id,),
    ).fetchall()


def get_results(conn: psycopg.Connection, run_id: int) -> list[dict]:
    return conn.execute(
        "SELECT input_id, raw_output, latency_ms, tokens_in, tokens_out, cost "
        "FROM results WHERE run_id=%s ORDER BY input_id",
        (run_id,),
    ).fetchall()


def get_scores(conn: psycopg.Connection, benchmark_id: int) -> list[dict]:
    return conn.execute(
        "SELECT use_case, metric, mean, min, max FROM scores WHERE benchmark_id=%s",
        (benchmark_id,),
    ).fetchall()


def log(
    conn: psycopg.Connection,
    *,
    benchmark_id: int | None,
    run_id: int | None,
    level: str,
    event: str,
    detail: Any | None = None,
) -> None:
    conn.execute(
        "INSERT INTO run_logs (benchmark_id, run_id, level, event, detail) "
        "VALUES (%s,%s,%s,%s,%s)",
        (benchmark_id, run_id, level, event, Json(detail) if detail is not None else None),
    )
