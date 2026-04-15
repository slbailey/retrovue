"""Replace per-day partial unique with one active revision per channel.

INV-SINGLE-ACTIVE-REVISION-001: at most one ScheduleRevision with status='active'
per channel globally (not per broadcast_day).

Revision ID: sched_rev_one_active_ch_001
Revises: cun_render_requests_001
Create Date: 2026-04-14
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "sched_rev_one_active_ch_001"
down_revision: Union[str, Sequence[str], None] = "cun_render_requests_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_schedule_revisions_one_active")
    # Existing DBs may have multiple active revisions per channel (old per-day index).
    # Keep the newest by activated_at, supersede the rest so the new index can be built.
    op.execute(
        """
        UPDATE schedule_revisions sr
        SET status = 'superseded', superseded_at = now()
        WHERE sr.id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY channel_id
                           ORDER BY activated_at DESC NULLS LAST, created_at DESC
                       ) AS rn
                FROM schedule_revisions
                WHERE status = 'active'
            ) ranked
            WHERE rn > 1
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_schedule_revisions_one_active_per_channel
        ON schedule_revisions (channel_id)
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_schedule_revisions_one_active_per_channel")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_schedule_revisions_one_active
        ON schedule_revisions (channel_id, broadcast_day)
        WHERE status = 'active'
        """
    )
