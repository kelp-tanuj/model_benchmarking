"""mark drift re-runs so the leaderboard can exclude them

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-20
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE benchmarks ADD COLUMN is_drift BOOLEAN NOT NULL DEFAULT false")
    op.execute("CREATE INDEX ix_benchmarks_leaderboard ON benchmarks (use_case, status, is_drift)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benchmarks_leaderboard")
    op.execute("ALTER TABLE benchmarks DROP COLUMN is_drift")
