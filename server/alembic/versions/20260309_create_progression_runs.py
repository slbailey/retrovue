"""Create progression_runs table for canonical episode progression.

Contract: docs/contracts/episode_progression.md

Progression runs store the anchor state for deterministic calendar-based
episode selection.  Lookup key: (channel_id, run_id) where run_id is
unique per active channel.

Revision ID: 20260309_progression_runs
Revises: 20260306_serial_runs
Create Date: 2026-03-09 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260309_progression_runs"
down_revision: Union[str, Sequence[str], None] = "20260306_serial_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "progression_runs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("content_source_id", sa.Text(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column(
            "anchor_episode_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("placement_days", sa.SmallInteger(), nullable=False),
        sa.Column(
            "exhaustion_policy",
            sa.String(20),
            nullable=False,
            server_default="wrap",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Constraints
        sa.CheckConstraint(
            "placement_days >= 1 AND placement_days <= 127",
            name="ck_progression_runs_placement_days_range",
        ),
        sa.CheckConstraint(
            "anchor_episode_index >= 0",
            name="ck_progression_runs_anchor_ep_nonneg",
        ),
        sa.CheckConstraint(
            "exhaustion_policy IN ('wrap', 'hold_last', 'stop')",
            name="ck_progression_runs_exhaustion_policy_valid",
        ),
    )
    # Unique active run per (channel_id, run_id)
    op.create_index(
        "uq_progression_run_active",
        "progression_runs",
        ["channel_id", "run_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "ix_progression_runs_channel_id",
        "progression_runs",
        ["channel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_progression_runs_channel_id", table_name="progression_runs")
    op.drop_index("uq_progression_run_active", table_name="progression_runs")
    op.drop_table("progression_runs")
