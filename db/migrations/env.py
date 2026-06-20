"""Alembic environment. URL comes from common.config (env / .env). Raw-SQL migrations, so
no autogenerate / target_metadata. Offline mode (`--sql`) works without a live DB."""

from __future__ import annotations

from alembic import context

from common.config import settings

config = context.config
target_metadata = None


def _url() -> str | None:
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url() or "postgresql://offline/offline",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    url = _url()
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set — put your Neon connection string in .env before migrating."
        )
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
