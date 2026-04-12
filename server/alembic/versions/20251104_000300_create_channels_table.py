from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

"""
Create channels table.

Revision ID: 20251104_000300_channels
Revises: 20251102_asset_meta
Create Date: 2025-11-04 00:03:00.000000
"""


# revision identifiers, used by Alembic.
revision: str = "20251104_000300_channels"
down_revision: str | None = "20251102_asset_meta"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Ensure enum exists once; prevent duplicate creation on reruns
    channel_kind = PG_ENUM(
        "network", "premium", "specialty", name="channel_kind", create_type=False
    )
    channel_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=255), nullable=False),
        sa.Column("grid_block_minutes", sa.Integer(), nullable=False),
        sa.Column("kind", channel_kind, nullable=False),
        sa.Column("programming_day_start", sa.Time(timezone=False), nullable=False),
        sa.Column("block_start_offsets_minutes", postgresql.JSONB, nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="chk_channels_slug_kebab_lower"
        ),
        sa.CheckConstraint(
            "grid_block_minutes IN (15, 30, 60)", name="chk_channels_grid_block_minutes"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(block_start_offsets_minutes) = 'array' AND "
            "jsonb_array_length(block_start_offsets_minutes) > 0",
            name="chk_channels_offsets_nonempty_array",
        ),
    )

    # SQL-level unique index on slug
    op.create_index("ix_channels_slug", "channels", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_channels_slug", table_name="channels")
    op.drop_table("channels")

    # Drop enum type if unused
    channel_kind = PG_ENUM(
        "network", "premium", "specialty", name="channel_kind", create_type=False
    )
    channel_kind.drop(op.get_bind(), checkfirst=True)



