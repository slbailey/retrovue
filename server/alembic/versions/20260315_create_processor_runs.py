"""Create processor_runs table (Phase 4 execution history).

Contract: ProcessorExecutionContract. One row per processor execution; immutable history.
Revision ID: 20260315_proc_runs
Revises: 20260315_proc_jobs
Create Date: 2026-03-15
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260315_proc_runs"
down_revision: str | Sequence[str] | None = "20260315_proc_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processor_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("processor_id", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("processor_version", sa.String(64), nullable=True),
        sa.Column("input_fingerprint", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "processor_runs_job_id_fkey",
        "processor_runs",
        "processor_jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_processor_runs_job_id", "processor_runs", ["job_id"], unique=False)
    op.create_index(
        "ix_processor_runs_processor_target",
        "processor_runs",
        ["processor_id", "target_type", "target_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_processor_runs_processor_target", table_name="processor_runs")
    op.drop_index("ix_processor_runs_job_id", table_name="processor_runs")
    op.drop_table("processor_runs")
