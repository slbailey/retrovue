"""Create processor_jobs table (Phase 3 job queue).

Contract: ProcessorJobQueueContract. One row per (target_type, target_id) when pending/running.
Revision ID: 20260315_proc_jobs
Revises: 20260315_assets_sid
Create Date: 2026-03-15
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260315_proc_jobs"
down_revision: str | Sequence[str] | None = "20260315_assets_sid"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processor_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_processor_jobs_status_priority",
        "processor_jobs",
        ["status", "priority"],
        unique=False,
    )
    # At most one pending or running job per (target_type, target_id).
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_processor_jobs_one_active_per_target
            ON processor_jobs (target_type, target_id)
            WHERE status IN ('pending', 'running')
            """
        )
    )


def downgrade() -> None:
    op.drop_index("uq_processor_jobs_one_active_per_target", table_name="processor_jobs")
    op.drop_index("ix_processor_jobs_status_priority", table_name="processor_jobs")
    op.drop_table("processor_jobs")
