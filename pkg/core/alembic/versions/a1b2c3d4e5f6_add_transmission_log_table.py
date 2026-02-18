"""Add transmission_log table

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-02-18 07:00:00.000000

Contract: docs/contracts/runtime/TransmissionLogPersistenceContract.md
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transmission_log",
        sa.Column("block_id", sa.String(255), nullable=False, primary_key=True),
        sa.Column("channel_slug", sa.String(255), nullable=False),
        sa.Column("broadcast_day", sa.Date(), nullable=False),
        sa.Column("start_utc_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_utc_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "segments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_transmission_log_channel_day",
        "transmission_log",
        ["channel_slug", "broadcast_day"],
    )


def downgrade() -> None:
    op.drop_index("ix_transmission_log_channel_day", table_name="transmission_log")
    op.drop_table("transmission_log")
