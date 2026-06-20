"""dead-letter support for the teams_inbox consumer

Adds an attempts counter + last_error so a poison row (handler keeps raising) is retried a
bounded number of times and then marked processed (dead-lettered) instead of looping forever.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-20
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE teams_inbox ADD COLUMN attempts INT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE teams_inbox ADD COLUMN last_error TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE teams_inbox DROP COLUMN last_error")
    op.execute("ALTER TABLE teams_inbox DROP COLUMN attempts")
