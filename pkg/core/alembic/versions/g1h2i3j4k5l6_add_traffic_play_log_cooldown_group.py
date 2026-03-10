"""Add cooldown_group column to traffic_play_log.

INV-TRAFFIC-GROUP-COOLDOWN-001: When multiple interstitial assets share a
cooldown group (e.g. multiple trailers for the same movie), playing any one
cools the entire group.  The group is derived from the filename at ingest.

Revision ID: g1h2i3j4k5l6
Revises: f7a8b9c0d1e2
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = "g1h2i3j4k5l6"
down_revision = "20260309_progression_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "traffic_play_log",
        sa.Column("cooldown_group", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_traffic_play_log_channel_group",
        "traffic_play_log",
        ["channel_slug", "cooldown_group", "played_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_traffic_play_log_channel_group", table_name="traffic_play_log")
    op.drop_column("traffic_play_log", "cooldown_group")
