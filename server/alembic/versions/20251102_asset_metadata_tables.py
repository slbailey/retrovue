from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

"""
Create child metadata tables for assets.

Revision ID: 20251102_asset_meta
Revises: 20251101_000200
Create Date: 2025-11-02 00:00:00.000000
"""


# revision identifiers, used by Alembic.
revision: str = "20251102_asset_meta"
down_revision: str | None = "20251101_000200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # editorial
    op.create_table(
        "asset_editorial",
        sa.Column(
            "asset_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # probed
    op.create_table(
        "asset_probed",
        sa.Column(
            "asset_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # station ops
    op.create_table(
        "asset_station_ops",
        sa.Column(
            "asset_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # relationships
    op.create_table(
        "asset_relationships",
        sa.Column(
            "asset_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # sidecar (the merged/validated one)
    op.create_table(
        "asset_sidecar",
        sa.Column(
            "asset_uuid",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("asset_sidecar")
    op.drop_table("asset_relationships")
    op.drop_table("asset_station_ops")
    op.drop_table("asset_probed")
    op.drop_table("asset_editorial")


