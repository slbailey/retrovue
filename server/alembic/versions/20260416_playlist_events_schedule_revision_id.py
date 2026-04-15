"""Add schedule_revision_id to playlist_events for Tier-2 provenance.

INV-SCHEDULE-CANONICAL-DERIVATION-001 / playlog: future PlaylistEvent rows are
attributable to the active ScheduleRevision that generated them.

Revision ID: playlist_events_sched_rev_001
Revises: schedule_items_no_overlap_001
Create Date: 2026-04-16
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "playlist_events_sched_rev_001"
down_revision: Union[str, Sequence[str], None] = "schedule_items_no_overlap_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "playlist_events",
        sa.Column(
            "schedule_revision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("schedule_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_playlist_events_schedule_revision_id",
        "playlist_events",
        ["schedule_revision_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_playlist_events_schedule_revision_id", table_name="playlist_events")
    op.drop_column("playlist_events", "schedule_revision_id")
