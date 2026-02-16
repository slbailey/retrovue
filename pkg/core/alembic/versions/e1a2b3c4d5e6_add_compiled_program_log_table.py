"""Add compiled_program_log table

Revision ID: e1a2b3c4d5e6
Revises: d26f5c803f70
Create Date: 2026-02-16 18:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "e1a2b3c4d5e6"
down_revision = "20260126_zones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compiled_program_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("broadcast_day", sa.Date, nullable=False),
        sa.Column("schedule_hash", sa.String(255), nullable=False),
        sa.Column("compiled_json", JSONB, nullable=False),
        sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "broadcast_day", name="uq_compiled_program_log_channel_day"),
        sa.Index("ix_compiled_program_log_channel_id", "channel_id"),
        sa.Index("ix_compiled_program_log_broadcast_day", "broadcast_day"),
    )


def downgrade() -> None:
    op.drop_table("compiled_program_log")
