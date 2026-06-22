"""daemon heartbeat table so the admin can show live worker status

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE daemon_status (
            name TEXT PRIMARY KEY,
            last_beat TIMESTAMPTZ NOT NULL DEFAULT now(),
            detail JSONB
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS daemon_status")
