from __future__ import annotations

import sqlalchemy as sa
from alembic import op

"""
Drop timezone column from channels; channels use local TIME anchor and UTC storage elsewhere.

Revision ID: 20251104_000400_drop_tz
Revises: 20251104_000300_channels
Create Date: 2025-11-04 00:40:00.000000
"""

# revision identifiers, used by Alembic.
revision: str = "20251104_000400_drop_tz"
down_revision: str | None = "20251104_000300_channels"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        try:
            batch_op.drop_column("timezone")
        except Exception:
            # Column may already be absent
            pass


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(sa.Column("timezone", sa.String(length=255), nullable=False, server_default="UTC"))
        # Remove default after backfill
        op.execute("ALTER TABLE channels ALTER COLUMN timezone DROP DEFAULT")
