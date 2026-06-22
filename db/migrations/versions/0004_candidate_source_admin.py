"""allow 'admin' as a candidate source (manual enqueue from the admin app)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-22
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE candidates DROP CONSTRAINT IF EXISTS candidates_source_check")
    op.execute(
        "ALTER TABLE candidates ADD CONSTRAINT candidates_source_check "
        "CHECK (source IN ('openrouter','teams','admin'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE candidates DROP CONSTRAINT IF EXISTS candidates_source_check")
    op.execute(
        "ALTER TABLE candidates ADD CONSTRAINT candidates_source_check "
        "CHECK (source IN ('openrouter','teams'))"
    )
