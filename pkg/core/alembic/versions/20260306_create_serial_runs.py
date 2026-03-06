"""Create serial_runs table for deterministic serial episode progression.

Contract: docs/contracts/runtime/INV-SERIAL-EPISODE-PROGRESSION.md

Revision ID: 20260306_serial_runs
Revises: 20260304_channel_active_ptr
Create Date: 2026-03-06 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "20260306_serial_runs"
down_revision: Union[str, Sequence[str], None] = "20260304_channel_active_ptr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "serial_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_name", sa.Text(), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("placement_time", sa.Time(), nullable=False),
        sa.Column("placement_days", sa.SmallInteger(), nullable=False),
        sa.Column("content_source_id", sa.Text(), nullable=False),
        sa.Column("content_source_type", sa.String(50), nullable=False),
        sa.Column("anchor_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anchor_episode_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progression_mode", sa.String(20), nullable=False, server_default="serial"),
        sa.Column("wrap_policy", sa.String(20), nullable=False, server_default="wrap"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Constraints
        sa.CheckConstraint("placement_days >= 1 AND placement_days <= 127", name="ck_serial_runs_placement_days_range"),
        sa.CheckConstraint("anchor_episode_index >= 0", name="ck_serial_runs_anchor_ep_nonneg"),
    )
    # PI-001: At most one active run per placement identity
    op.create_index(
        "uq_serial_run_active_placement",
        "serial_runs",
        ["channel_id", "placement_time", "placement_days", "content_source_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index("ix_serial_runs_channel_id", "serial_runs", ["channel_id"])
    op.create_index("ix_serial_runs_active", "serial_runs", ["channel_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_serial_runs_active", table_name="serial_runs")
    op.drop_index("ix_serial_runs_channel_id", table_name="serial_runs")
    op.drop_index("uq_serial_run_active_placement", table_name="serial_runs")
    op.drop_table("serial_runs")
