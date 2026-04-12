"""Create processor_outputs table (Phase 5 flexible metadata).

Contract: ProcessorMetadataContract. One row per (processor_id, target_type, target_id).
Revision ID: 20260315_proc_out
Revises: 20260315_proc_runs
Create Date: 2026-03-15
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260315_proc_out"
down_revision: str | Sequence[str] | None = "20260315_proc_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processor_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("processor_id", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_processor_outputs_processor_target",
        "processor_outputs",
        ["processor_id", "target_type", "target_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_processor_outputs_processor_target", table_name="processor_outputs")
    op.drop_table("processor_outputs")
