"""add episode scope to agent sessions

Revision ID: c7f49b8e2d10
Revises: 78d31ac4f962
Create Date: 2026-08-27 10:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7f49b8e2d10"
down_revision: str | Sequence[str] | None = "78d31ac4f962"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("episode", sa.Integer(), nullable=True))
        batch_op.create_index(
            "idx_agent_sessions_project_episode",
            ["project_name", "episode", "updated_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_sessions", schema=None) as batch_op:
        batch_op.drop_index("idx_agent_sessions_project_episode")
        batch_op.drop_column("episode")
