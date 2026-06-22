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
    is_drift: bool = False,
) -> int:
    row = conn.execute(
        """
        INSERT INTO benchmarks
            (slug, use_case, route, provider, judge_model, judge_version, n_reps,
             is_baseline, is_drift, started_at, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), 'running')
        RETURNING benchmark_id
        """,
        (slug, use_case, route, provider, judge_model, judge_version, n_reps, is_baseline,
         is_drift),
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


def upsert_candidate(
    conn: psycopg.Connection,
    *,
    slug: str,
    source: str,
    status: str,
    foundry_available: bool | None = None,
    foundry_model_id: str | None = None,
    decided_by: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO candidates (slug, source, status, foundry_available, foundry_model_id,
                                decided_by, decided_at)
        VALUES (%s,%s,%s,%s,%s,%s, CASE WHEN %s::text IS NULL THEN NULL ELSE now() END)
        ON CONFLICT (slug) DO UPDATE SET
            status=EXCLUDED.status,
            foundry_available=COALESCE(EXCLUDED.foundry_available, candidates.foundry_available),
            foundry_model_id=COALESCE(EXCLUDED.foundry_model_id, candidates.foundry_model_id),
            decided_by=COALESCE(EXCLUDED.decided_by, candidates.decided_by),
            decided_at=CASE WHEN EXCLUDED.decided_by IS NOT NULL THEN now()
                            ELSE candidates.decided_at END
        """,
        (slug, source, status, foundry_available, foundry_model_id, decided_by, decided_by),
    )


def set_candidate_status(
    conn: psycopg.Connection, slug: str, status: str, decided_by: str | None = None
) -> int:
    """Returns the number of rows updated (0 = no such candidate slug)."""
    cur = conn.execute(
        "UPDATE candidates SET status=%s, decided_by=COALESCE(%s, decided_by), "
        "decided_at=CASE WHEN %s::text IS NOT NULL THEN now() ELSE decided_at END WHERE slug=%s",
        (status, decided_by, decided_by, slug),
    )
    return cur.rowcount


def get_candidate(conn: psycopg.Connection, slug: str) -> dict | None:
    return conn.execute("SELECT * FROM candidates WHERE slug=%s", (slug,)).fetchone()


def list_candidates(conn: psycopg.Connection, status: str | None = None) -> list[dict]:
    if status:
        return conn.execute(
            "SELECT * FROM candidates WHERE status=%s ORDER BY created_at DESC", (status,)
        ).fetchall()
    return conn.execute("SELECT * FROM candidates ORDER BY created_at DESC").fetchall()


# --- OpenRouter catalog sync (discovery radar) --------------------------------------

def count_openrouter_models(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) AS n FROM openrouter_models").fetchone()["n"]


def db_now(conn: psycopg.Connection):
    """The database clock — use as the sync cutoff so retirement diffs are skew-free."""
    return conn.execute("SELECT now() AS t").fetchone()["t"]


def upsert_openrouter_model(
    conn: psycopg.Connection,
    *,
    slug: str,
    name: str | None,
    modality: str | None,
    context_length: int | None,
    price_prompt: float | None,
    price_completion: float | None,
    raw: Any,
) -> bool:
    """Idempotent catalog upsert; returns True iff the row was newly inserted (a fresh insert
    has first_seen == last_seen == this transaction's now(); an update moves last_seen only)."""
    row = conn.execute(
        """
        INSERT INTO openrouter_models
            (slug, name, modality, context_length, price_prompt, price_completion, raw,
             first_seen, last_seen)
        VALUES (%s,%s,%s,%s,%s,%s,%s, now(), now())
        ON CONFLICT (slug) DO UPDATE SET
            name=EXCLUDED.name, modality=EXCLUDED.modality,
            context_length=EXCLUDED.context_length, price_prompt=EXCLUDED.price_prompt,
            price_completion=EXCLUDED.price_completion, raw=EXCLUDED.raw, last_seen=now()
        RETURNING (first_seen = last_seen) AS is_new
        """,
        (slug, name, modality, context_length, price_prompt, price_completion, Json(raw)),
    ).fetchone()
    return bool(row["is_new"])


def get_openrouter_model(conn: psycopg.Connection, slug: str) -> dict | None:
    return conn.execute(
        "SELECT slug, name, modality, context_length, price_prompt, price_completion "
        "FROM openrouter_models WHERE slug=%s",
        (slug,),
    ).fetchone()


def get_retired_important(conn: psycopg.Connection, cutoff) -> list[str]:
    """Models NOT seen in the latest sync (last_seen < cutoff) that we actually care about —
    ones we've benchmarked or that back a baseline. Others are recorded but not alerted (noise).

    NOTE: this matches on exact slug, so it stays dormant until `model_aliases` bridges the
    OpenRouter namespace (e.g. google/…) and our benchmark/baseline namespace (e.g. gemini/…).
    That aliasing lands in phase 5; the diff logic itself is verified."""
    rows = conn.execute(
        """
        SELECT om.slug FROM openrouter_models om
        WHERE om.last_seen < %s
          AND (om.slug IN (SELECT slug FROM benchmarks)
               OR om.slug IN (SELECT model FROM baselines WHERE model IS NOT NULL))
        ORDER BY om.slug
        """,
        (cutoff,),
    ).fetchall()
    return [r["slug"] for r in rows]


# --- Web discovery: intel + aliases ---------------------------------------------------

def upsert_discovered_model(
    conn: psycopg.Connection,
    *,
    slug: str,
    canonical_name: str,
    provider: str | None,
    est_cost: str | None,
    performance: str | None,
    attributes: str | None,
    source_urls: Any | None,
    possible_duplicate_of: str | None,
    raw: Any | None,
) -> None:
    """Idempotent on slug (record-as-you-go safe); coalesces fields, bumps last_seen."""
    conn.execute(
        """
        INSERT INTO discovered_models
            (slug, canonical_name, provider, est_cost, performance, attributes, source_urls,
             possible_duplicate_of, raw, first_seen, last_seen)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), now())
        ON CONFLICT (slug) DO UPDATE SET
            canonical_name=EXCLUDED.canonical_name,
            provider=COALESCE(EXCLUDED.provider, discovered_models.provider),
            est_cost=COALESCE(EXCLUDED.est_cost, discovered_models.est_cost),
            performance=COALESCE(EXCLUDED.performance, discovered_models.performance),
            attributes=COALESCE(EXCLUDED.attributes, discovered_models.attributes),
            source_urls=COALESCE(EXCLUDED.source_urls, discovered_models.source_urls),
            possible_duplicate_of=COALESCE(EXCLUDED.possible_duplicate_of,
                                           discovered_models.possible_duplicate_of),
            raw=EXCLUDED.raw, last_seen=now()
        """,
        (slug, canonical_name, provider, est_cost, performance, attributes,
         Json(source_urls) if source_urls is not None else None,
         possible_duplicate_of, Json(raw) if raw is not None else None),
    )


def get_discovered_model(conn: psycopg.Connection, slug: str) -> dict | None:
    return conn.execute("SELECT * FROM discovered_models WHERE slug=%s", (slug,)).fetchone()


def list_discovered_models(conn: psycopg.Connection, status: str | None = None) -> list[dict]:
    """Web-discovered models joined with their candidate status (for the admin app)."""
    if status:
        return conn.execute(
            "SELECT d.*, c.status, c.source, c.decided_by FROM discovered_models d "
            "JOIN candidates c USING (slug) WHERE c.status=%s ORDER BY d.first_seen DESC",
            (status,),
        ).fetchall()
    return conn.execute(
        "SELECT d.*, c.status, c.source, c.decided_by FROM discovered_models d "
        "JOIN candidates c USING (slug) ORDER BY d.first_seen DESC"
    ).fetchall()


def add_alias(
    conn: psycopg.Connection,
    *,
    openrouter_slug: str,
    native_provider: str | None = None,
    native_model_id: str | None = None,
) -> None:
    """Bridge an OpenRouter slug to a native identity (idempotent on openrouter_slug)."""
    conn.execute(
        """
        INSERT INTO model_aliases (openrouter_slug, native_provider, native_model_id)
        VALUES (%s,%s,%s)
        ON CONFLICT (openrouter_slug) DO UPDATE SET
            native_provider=COALESCE(EXCLUDED.native_provider, model_aliases.native_provider),
            native_model_id=COALESCE(EXCLUDED.native_model_id, model_aliases.native_model_id)
        """,
        (openrouter_slug, native_provider, native_model_id),
    )


def all_aliases(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT openrouter_slug, native_provider, native_model_id FROM model_aliases"
    ).fetchall()


def all_openrouter_identities(conn: psycopg.Connection) -> list[dict]:
    """Slug+name for every catalog row — caller computes normkeys in code for fuzzy matching."""
    return conn.execute("SELECT slug, name FROM openrouter_models").fetchall()


def has_event(conn: psycopg.Connection, event: str, slug: str) -> bool:
    """Has a run_logs event of this kind already been recorded for this slug? (alert dedup)."""
    return conn.execute(
        "SELECT 1 FROM run_logs WHERE event=%s AND detail->>'slug'=%s LIMIT 1",
        (event, slug),
    ).fetchone() is not None


def search_openrouter(conn: psycopg.Connection, query: str, limit: int = 10) -> list[dict]:
    """Fuzzy name/slug match over the OpenRouter catalog (the sole discovery radar).

    The query is a bound parameter (no SQL injection); we additionally escape LIKE
    metacharacters so a user typing %/_ can't turn the search into a wildcard over-match.
    """
    esc = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{esc}%"
    return conn.execute(
        r"SELECT slug, name, context_length FROM openrouter_models "
        r"WHERE lower(slug) LIKE %s ESCAPE '\' OR lower(name) LIKE %s ESCAPE '\' "
        r"ORDER BY slug LIMIT %s",
        (like, like, limit),
    ).fetchall()


# --- Teams inbound poll table ---

def add_teams_inbox(conn: psycopg.Connection, kind: str, payload: dict) -> int:
    row = conn.execute(
        "INSERT INTO teams_inbox (kind, payload) VALUES (%s,%s) RETURNING id",
        (kind, Json(payload)),
    ).fetchone()
    return row["id"]


def get_unprocessed_inbox(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    return conn.execute(
        "SELECT id, kind, payload FROM teams_inbox WHERE processed_at IS NULL "
        "ORDER BY id LIMIT %s",
        (limit,),
    ).fetchall()


def mark_inbox_processed(
    conn: psycopg.Connection, inbox_id: int, error: str | None = None
) -> None:
    """Terminal: row will not be re-selected. `error` set when dead-lettering a bad row."""
    conn.execute(
        "UPDATE teams_inbox SET processed_at=now(), last_error=%s WHERE id=%s",
        (error, inbox_id),
    )


def bump_inbox_attempt(conn: psycopg.Connection, inbox_id: int, error: str | None) -> int:
    """Record a transient failure; returns the new attempts count (caller dead-letters at N)."""
    row = conn.execute(
        "UPDATE teams_inbox SET attempts = attempts + 1, last_error=%s WHERE id=%s "
        "RETURNING attempts",
        (error, inbox_id),
    ).fetchone()
    return row["attempts"] if row else 0


def list_use_cases(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT use_case FROM benchmarks WHERE status='done' ORDER BY use_case"
    ).fetchall()
    return [r["use_case"] for r in rows]


def get_benchmarks(conn: psycopg.Connection, use_case: str) -> list[dict]:
    """Completed candidate/baseline benchmarks for a use case (drift re-runs excluded)."""
    return conn.execute(
        """
        SELECT benchmark_id, slug, provider, route, is_baseline, judge_model, judge_version,
               n_reps, finished_at
        FROM benchmarks
        WHERE use_case=%s AND status='done' AND is_drift = false
        ORDER BY is_baseline DESC, finished_at DESC
        """,
        (use_case,),
    ).fetchall()


# --- Admin monitoring reads ----------------------------------------------------------

def get_recent_benchmarks(conn: psycopg.Connection, limit: int = 50) -> list[dict]:
    """All benchmarks (any status, incl. running/failed/drift) for the admin monitor."""
    return conn.execute(
        """
        SELECT benchmark_id, slug, use_case, provider, route, status, is_baseline, is_drift,
               n_reps, started_at, finished_at
        FROM benchmarks ORDER BY started_at DESC LIMIT %s
        """,
        (limit,),
    ).fetchall()


def get_runs(conn: psycopg.Connection, benchmark_id: int) -> list[dict]:
    return conn.execute(
        "SELECT run_id, rep_index, status, started_at, finished_at FROM runs "
        "WHERE benchmark_id=%s ORDER BY rep_index",
        (benchmark_id,),
    ).fetchall()


def get_recent_logs(conn: psycopg.Connection, limit: int = 100) -> list[dict]:
    return conn.execute(
        "SELECT ts, level, event, benchmark_id, run_id, detail FROM run_logs "
        "ORDER BY ts DESC LIMIT %s",
        (limit,),
    ).fetchall()


def get_catalog_status(conn: psycopg.Connection) -> dict:
    return conn.execute(
        "SELECT count(*) AS n, max(last_seen) AS last_sync, max(first_seen) AS newest "
        "FROM openrouter_models"
    ).fetchone()


def get_scores_for_use_case(conn: psycopg.Connection, use_case: str) -> list[dict]:
    return conn.execute(
        "SELECT benchmark_id, metric, mean, min, max FROM scores WHERE use_case=%s",
        (use_case,),
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
