"""Create enricher_runs table for per-enricher execution tracking.

Contract: INV-ENRICHER-OBSERVABILITY-001. One row per enricher per asset per execution.
Provides queryable per-enricher granularity that ProcessorJob does not expose.

Revision ID: enricher_runs_001
Revises: drop_crud_island_001
Create Date: 2026-04-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "enricher_runs_001"
down_revision: str | Sequence[str] | None = "drop_crud_island_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "enricher_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.uuid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enricher_name", sa.String(64), nullable=False),
        sa.Column("enricher_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_enricher_runs_asset_id", "enricher_runs", ["asset_id"])
    op.create_index(
        "ix_enricher_runs_asset_enricher",
        "enricher_runs",
        ["asset_id", "enricher_name"],
    )
    op.create_index(
        "ix_enricher_runs_enricher_version",
        "enricher_runs",
        ["enricher_name", "enricher_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_enricher_runs_enricher_version", table_name="enricher_runs")
    op.drop_index("ix_enricher_runs_asset_enricher", table_name="enricher_runs")
    op.drop_index("ix_enricher_runs_asset_id", table_name="enricher_runs")
    op.drop_table("enricher_runs")
