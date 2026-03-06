"""Add channel_active_revisions pointer table.

Revision ID: 20260304_channel_active_ptr
Revises: 20260303_sched_rev
Create Date: 2026-03-04 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "20260304_channel_active_ptr"
down_revision: Union[str, Sequence[str], None] = "20260303_sched_rev"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_active_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_day", sa.Date(), nullable=False),
        sa.Column(
            "schedule_revision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("schedule_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("channel_id", "broadcast_day", name="uq_channel_active_revisions_channel_day"),
    )

    op.create_index(
        "ix_channel_active_revisions_channel_day",
        "channel_active_revisions",
        ["channel_id", "broadcast_day"],
    )

    # Backfill pointers for existing active revisions.
    op.execute(
        """
        INSERT INTO channel_active_revisions (channel_id, broadcast_day, schedule_revision_id, updated_at)
        SELECT sr.channel_id, sr.broadcast_day, sr.id, now()
        FROM schedule_revisions sr
        WHERE sr.status = 'active'
        ON CONFLICT (channel_id, broadcast_day)
        DO UPDATE SET
            schedule_revision_id = EXCLUDED.schedule_revision_id,
            updated_at = now()
        """
    )


def downgrade() -> None:
    op.drop_index("ix_channel_active_revisions_channel_day", table_name="channel_active_revisions")
    op.drop_table("channel_active_revisions")
