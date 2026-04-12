"""Drop retired CRUD island tables (SchedulePlan, Zone, Program, SchedulePlanLabel)

INV-CRUD-ISLAND-RETIRED-001 / RETA-94

These tables supported the SchedulePlan CRUD island which was retired per
RETA-88 Option B. The DSL + ScheduleRevision/ScheduleItem path is the sole
scheduling authority. All CRUD surfaces (CLI, API, use cases) have been
removed; this migration drops the backing tables.

Tables dropped (order respects FK dependencies):
- programs (FK -> schedule_plans, schedule_plan_labels, channels)
- zones (FK -> schedule_plans)
- schedule_plans (FK -> channels)
- schedule_plan_labels (no FK dependencies from other live tables)

Revision ID: drop_crud_island_001
Revises: pm_source_scoped_001
Create Date: 2026-04-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "drop_crud_island_001"
down_revision: str | Sequence[str] | None = "pm_source_scoped_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop in dependency order: children first, then parents
    op.drop_table("programs")
    op.drop_table("zones")
    op.drop_table("schedule_plans")
    op.drop_table("schedule_plan_labels")


def downgrade() -> None:
    # Recreate schedule_plan_labels (no FK deps)
    op.create_table(
        "schedule_plan_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_schedule_plan_labels_name", "schedule_plan_labels", ["name"])
    op.create_index("ix_schedule_plan_labels_category", "schedule_plan_labels", ["category"])

    # Recreate schedule_plans
    op.create_table(
        "schedule_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("cron_expression", sa.Text, nullable=True),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "name", name="uq_schedule_plans_channel_name"),
        sa.CheckConstraint("priority >= 0", name="chk_schedule_plans_priority_non_negative"),
    )
    op.create_index("ix_schedule_plans_channel_id", "schedule_plans", ["channel_id"])
    op.create_index("ix_schedule_plans_name", "schedule_plans", ["name"])
    op.create_index("ix_schedule_plans_is_active", "schedule_plans", ["is_active"])

    # Recreate zones
    op.create_table(
        "zones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schedule_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("start_time", sa.Time(timezone=False), nullable=False),
        sa.Column("end_time", sa.Time(timezone=False), nullable=False),
        sa.Column("schedulable_assets", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("day_filters", postgresql.JSONB, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("effective_start", sa.Date, nullable=True),
        sa.Column("effective_end", sa.Date, nullable=True),
        sa.Column("dst_policy", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("plan_id", "name", name="uq_zones_plan_name"),
        sa.CheckConstraint(
            "dst_policy IS NULL OR dst_policy IN ('reject', 'shrink_one_block', 'expand_one_block')",
            name="chk_zones_dst_policy_valid",
        ),
        sa.CheckConstraint(
            "(effective_start IS NULL AND effective_end IS NULL) OR "
            "(effective_start IS NULL) OR (effective_end IS NULL) OR "
            "(effective_start <= effective_end)",
            name="chk_zones_effective_range",
        ),
    )
    op.create_index("ix_zones_plan_id", "zones", ["plan_id"])
    op.create_index("ix_zones_enabled", "zones", ["enabled"])
    op.create_index("ix_zones_start_time", "zones", ["start_time"])

    # Recreate programs
    op.create_table(
        "programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schedule_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("content_ref", sa.Text, nullable=False),
        sa.Column("label_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schedule_plan_labels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("episode_policy", sa.String(50), nullable=True),
        sa.Column("playback_rules", sa.JSON, nullable=True),
        sa.Column("operator_intent", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_programs_channel_id", "programs", ["channel_id"])
    op.create_index("ix_programs_plan_id", "programs", ["plan_id"])
    op.create_index("ix_programs_start_time", "programs", ["plan_id", "start_time"])
    op.create_index("ix_programs_label_id", "programs", ["label_id"])
