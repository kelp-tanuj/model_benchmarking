"""Postgres connection helper (psycopg 3). Thin on purpose; the repo layer builds on this."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row

from common.config import settings


def _require_url() -> str:
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Put your Neon connection string in a local .env "
            "(see .env.example) before running anything that touches the database."
        )
    return settings.database_url


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Yield a connection with dict rows; commits on clean exit, rolls back on error."""
    conn = psycopg.connect(_require_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
