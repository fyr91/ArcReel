"""add company asset catalog state

Revision ID: 69e2f4c8a1bd
Revises: 78d31ac4f962
Create Date: 2026-08-29 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "69e2f4c8a1bd"
down_revision: str | Sequence[str] | None = "78d31ac4f962"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch_op:
        batch_op.add_column(sa.Column("external_origin", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("external_version", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("external_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("external_owner_id", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("external_owner_name", sa.String(length=200), nullable=True))

    op.create_table(
        "company_asset_checkpoints",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source", "asset_type"),
    )

    with op.batch_alter_table("arcreel_cloud_sessions") as batch_op:
        batch_op.add_column(sa.Column("access_token_encrypted", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True))

    op.drop_index("idx_background_jobs_one_active_per_type", table_name="background_jobs")
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.String(), server_default="default", nullable=False))
        batch_op.add_column(sa.Column("payload_json", sa.Text(), nullable=True))
    op.create_index(
        "idx_background_jobs_one_active_per_type",
        "background_jobs",
        ["job_type", "owner_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("idx_background_jobs_one_active_per_type", table_name="background_jobs")
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.drop_column("payload_json")
        batch_op.drop_column("owner_id")
    op.create_index(
        "idx_background_jobs_one_active_per_type",
        "background_jobs",
        ["job_type"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    with op.batch_alter_table("arcreel_cloud_sessions") as batch_op:
        batch_op.drop_column("access_token_expires_at")
        batch_op.drop_column("access_token_encrypted")

    op.drop_table("company_asset_checkpoints")
    with op.batch_alter_table("assets") as batch_op:
        batch_op.drop_column("external_owner_name")
        batch_op.drop_column("external_owner_id")
        batch_op.drop_column("external_status")
        batch_op.drop_column("external_version")
        batch_op.drop_column("external_origin")
