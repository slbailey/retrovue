"""Create cun_render_requests table for Coming Up Next render queue.

Contract: INV-CUN-SCHEDULE-SCOPED-001. Dedicated queue scoped to (channel, segment),
separate from processor_jobs. Supports SKIP LOCKED claim via partial indexes.

Revision ID: cun_render_requests_001
Revises: 251e64733e7b
Create Date: 2026-04-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cun_render_requests_001"
down_revision: str | Sequence[str] | None = "251e64733e7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cun_render_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "channel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_program_title", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("rendered_asset_path", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("channel_id", "segment_start_utc", name="uq_cun_channel_segment"),
    )

    # Partial index for SKIP LOCKED pending claim pattern
    op.execute(
        sa.text(
            """
            CREATE INDEX idx_cun_render_pending
            ON cun_render_requests (status, priority, created_at)
            WHERE status = 'pending'
            """
        )
    )

    # Partial index for content-hash cache dedup on completed renders
    op.execute(
        sa.text(
            """
            CREATE INDEX idx_cun_render_content_hash
            ON cun_render_requests (content_hash, status)
            WHERE status = 'completed'
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_cun_render_content_hash", table_name="cun_render_requests")
    op.drop_index("idx_cun_render_pending", table_name="cun_render_requests")
    op.drop_table("cun_render_requests")
