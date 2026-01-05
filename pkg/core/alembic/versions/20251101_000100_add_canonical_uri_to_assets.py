"""add canonical_uri to assets

Revision ID: 20251101_000100
Revises: 20251030_rename_path_mapping_collection_id_to_uuid
Create Date: 2025-11-01 00:01:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20251101_000100"
# Chain after the latest schema sync to avoid multiple heads
down_revision = "00c766d4a2e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add canonical_uri column (nullable for backfill)
    op.add_column("assets", sa.Column("canonical_uri", sa.Text(), nullable=True))
    # Index for collection + canonical_uri lookups
    op.create_index(
        "ix_assets_collection_canonical_uri",
        "assets",
        ["collection_uuid", "canonical_uri"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assets_collection_canonical_uri", table_name="assets")
    op.drop_column("assets", "canonical_uri")


