"""Create schedule_revisions, schedule_items tables and schedule_days VIEW

Revision ID: 20260303_sched_rev
Revises: 20260303_col_rename
Create Date: 2026-03-03 16:00:00.000000

Introduces ScheduleRevision as the immutable Tier-1 authority snapshot.
ScheduleItems are editorial schedule units belonging to exactly one revision.
schedule_days is a derived VIEW (not an owning table).

Key design decisions:
  - schedule_items does NOT carry channel_id or broadcast_day; those are
    inherited from the parent schedule_revision via FK join.  This prevents
    split-authority bugs (item claiming channel B inside revision for channel A).
  - Partial unique index uq_schedule_revisions_one_active enforces at most
    one active revision per (channel_id, broadcast_day).  Multiple drafts or
    superseded revisions may coexist, but only one can be status='active'.
  - No backfill: both tables start empty.  Existing ProgramLogDay rows are
    untouched and continue to serve as the compiled schedule cache.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "20260303_sched_rev"
down_revision: Union[str, Sequence[str], None] = "20260303_col_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── schedule_revisions ────────────────────────────────────────────
    op.create_table(
        "schedule_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_day", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.Text(), nullable=False,
            comment="Lifecycle: draft → active → superseded",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'superseded')",
            name="chk_schedule_revisions_status_valid",
        ),
    )

    op.create_index(
        "ix_schedule_revisions_channel_day",
        "schedule_revisions",
        ["channel_id", "broadcast_day"],
    )

    # Partial unique index: at most one active revision per channel per day.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_schedule_revisions_one_active
        ON schedule_revisions (channel_id, broadcast_day)
        WHERE status = 'active'
        """
    )

    # ── schedule_items ────────────────────────────────────────────────
    op.create_table(
        "schedule_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "schedule_revision_id", UUID(as_uuid=True),
            sa.ForeignKey("schedule_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("asset_id", UUID(as_uuid=True), nullable=True),
        sa.Column("collection_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "content_type", sa.Text(), nullable=False,
            comment="episode | movie | filler | bumper | promo | station_id",
        ),
        sa.Column("window_uuid", UUID(as_uuid=True), nullable=True),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("schedule_revision_id", "slot_index", name="uq_schedule_items_revision_slot"),
        sa.UniqueConstraint("schedule_revision_id", "start_time", name="uq_schedule_items_revision_start"),
    )

    op.create_index(
        "ix_schedule_items_revision_id",
        "schedule_items",
        ["schedule_revision_id"],
    )

    # ── schedule_days VIEW (derived, not an owning table) ─────────────
    op.execute(
        """
        CREATE VIEW schedule_days AS
        SELECT
            sr.channel_id,
            sr.broadcast_day,
            sr.id        AS schedule_revision_id,
            sr.status    AS revision_status,
            sr.activated_at,
            count(si.id) AS item_count
        FROM schedule_revisions sr
        LEFT JOIN schedule_items si ON si.schedule_revision_id = sr.id
        WHERE sr.status = 'active'
        GROUP BY sr.id, sr.channel_id, sr.broadcast_day, sr.status, sr.activated_at
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS schedule_days")
    op.drop_table("schedule_items")
    op.drop_table("schedule_revisions")
