"""web discovery radar: discovered_models intel table + candidates.source='web'

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-22
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE candidates DROP CONSTRAINT IF EXISTS candidates_source_check")
    op.execute(
        "ALTER TABLE candidates ADD CONSTRAINT candidates_source_check "
        "CHECK (source IN ('openrouter','teams','admin','web'))"
    )
    op.execute(
        """
        CREATE TABLE discovered_models (
            slug TEXT PRIMARY KEY REFERENCES candidates(slug) ON DELETE CASCADE,
            canonical_name TEXT NOT NULL,
            provider TEXT,
            est_cost TEXT,                 -- free-text: web costs are approximate/ranged
            performance TEXT,
            attributes TEXT,
            source_urls JSONB,
            possible_duplicate_of TEXT,    -- OpenRouter slug we suspect but did not auto-merge
            raw JSONB,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_discovered_models_provider ON discovered_models (provider)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discovered_models")
    op.execute("ALTER TABLE candidates DROP CONSTRAINT IF EXISTS candidates_source_check")
    op.execute(
        "ALTER TABLE candidates ADD CONSTRAINT candidates_source_check "
        "CHECK (source IN ('openrouter','teams','admin'))"
    )
