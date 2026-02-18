"""Add traffic management tables

Revision ID: f7a8b9c0d1e2
Revises: e1a2b3c4d5e6
Create Date: 2026-02-18 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── traffic_channel_policy ──
    # Per-channel rules for interstitial types, cooldowns, caps.
    # Keyed by channel slug (matches YAML channel config).
    op.create_table(
        "traffic_channel_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_slug", sa.String(255), nullable=False),
        sa.Column("allowed_types", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'[\"commercial\", \"promo\", \"station_id\", \"psa\", \"stinger\", \"bumper\", \"filler\"]'::jsonb")),
        sa.Column("default_cooldown_seconds", sa.Integer, nullable=False,
                  server_default=sa.text("3600")),
        sa.Column("type_cooldowns", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("max_plays_per_day", sa.Integer, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("channel_slug", name="uq_traffic_channel_policy_slug"),
    )

    # ── traffic_play_log ──
    # Every interstitial play on every channel.
    op.create_table(
        "traffic_play_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_slug", sa.String(255), nullable=False),
        sa.Column("asset_uuid", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("asset_uri", sa.Text, nullable=False),
        sa.Column("asset_type", sa.String(50), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("break_index", sa.Integer, nullable=True),
        sa.Column("block_id", sa.String(255), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=False),
    )

    op.create_index(
        "ix_traffic_play_log_channel_played",
        "traffic_play_log",
        ["channel_slug", "played_at"],
    )
    op.create_index(
        "ix_traffic_play_log_channel_asset",
        "traffic_play_log",
        ["channel_slug", "asset_uuid", "played_at"],
    )


def downgrade() -> None:
    op.drop_table("traffic_play_log")
    op.drop_table("traffic_channel_policy")
