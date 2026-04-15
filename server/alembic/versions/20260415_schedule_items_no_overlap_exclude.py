"""Reject overlapping [start, end) intervals per revision (trigger).

INV-SCHEDULE-NO-OVERLAP-001: overlapping schedule_items within the same
schedule_revision_id must be rejected at flush.

Uses a BEFORE INSERT/UPDATE trigger (no btree_gist extension — compatible with
DB roles that cannot CREATE EXTENSION).

Revision ID: schedule_items_no_overlap_001
Revises: sched_rev_one_active_ch_001
Create Date: 2026-04-15
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "schedule_items_no_overlap_001"
down_revision: Union[str, Sequence[str], None] = "sched_rev_one_active_ch_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_schedule_items_no_overlap()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM schedule_items o
            WHERE o.schedule_revision_id = NEW.schedule_revision_id
              AND (NEW.id IS NULL OR o.id <> NEW.id)
              AND tstzrange(
                    o.start_time,
                    o.start_time + (o.duration_sec * interval '1 second'),
                    '[)'
                  )
                  && tstzrange(
                    NEW.start_time,
                    NEW.start_time + (NEW.duration_sec * interval '1 second'),
                    '[)'
                  )
          ) THEN
            RAISE EXCEPTION 'INV-SCHEDULE-NO-OVERLAP-001: overlapping intervals in same revision'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER tr_schedule_items_no_overlap_biud
        BEFORE INSERT OR UPDATE ON schedule_items
        FOR EACH ROW EXECUTE FUNCTION check_schedule_items_no_overlap();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS tr_schedule_items_no_overlap_biud ON schedule_items"
    )
    op.execute("DROP FUNCTION IF EXISTS check_schedule_items_no_overlap()")
