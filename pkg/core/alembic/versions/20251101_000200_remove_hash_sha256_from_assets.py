"""
remove hash_sha256 from assets

Revision ID: 20251101_000200
Revises: 20251101_000100
Create Date: 2025-11-01 00:02:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251101_000200"
down_revision: str = "20251101_000100"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Drop hash_sha256 column if it exists
    with op.batch_alter_table("assets") as batch_op:
        try:
            batch_op.drop_column("hash_sha256")
        except Exception:
            # Column already absent; ignore
            pass


def downgrade() -> None:
    # Recreate hash_sha256 column (nullable)
    with op.batch_alter_table("assets") as batch_op:
        batch_op.add_column(sa.Column("hash_sha256", sa.String(length=64), nullable=True))


