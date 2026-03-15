"""Add source_id and fingerprint (file_size, file_mtime) to assets.

Phase 2 asset identity: (source_id, container_id, locator) per ASSET_IDENTITY_MIGRATION.md.
Backfill source_id from collections; then NOT NULL and uq_assets_source_container_locator.

Revision ID: 20260315_assets_sid
Revises: g1h2i3j4k5l6
Create Date: 2026-03-15

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260315_assets_sid"
down_revision: str | Sequence[str] | None = "g1h2i3j4k5l6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Add source_id nullable, no FK yet so backfill can run
    op.add_column(
        "assets",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # 2) Backfill from collections
    op.execute(
        sa.text(
            """
            UPDATE assets
            SET source_id = collections.source_id
            FROM collections
            WHERE collections.uuid = assets.collection_uuid
            """
        )
    )
    # 3) Make source_id NOT NULL (every asset has a collection with source_id)
    op.alter_column(
        "assets",
        "source_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    # 4) Add FK to sources
    op.create_foreign_key(
        "assets_source_id_fkey",
        "assets",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # 5) Fingerprint columns for reconciliation
    op.add_column(
        "assets",
        sa.Column("file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column("file_mtime", sa.Float(), nullable=True),
    )
    # 6) Contract identity unique constraint
    op.create_unique_constraint(
        "uq_assets_source_container_locator",
        "assets",
        ["source_id", "collection_uuid", "uri"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_assets_source_container_locator",
        "assets",
        type_="unique",
    )
    op.drop_column("assets", "file_mtime")
    op.drop_column("assets", "file_size")
    op.drop_constraint("assets_source_id_fkey", "assets", type_="foreignkey")
    op.alter_column(
        "assets",
        "source_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.drop_column("assets", "source_id")
