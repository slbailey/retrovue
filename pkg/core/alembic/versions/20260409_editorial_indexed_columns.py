"""Add indexed columns to asset_editorial for metadata consolidation.

Contract: docs/contracts/metadata_consolidation.md
Columns: series_title, season_number, episode_number, content_rating, production_year
Backfill: populate from existing JSONB payload.

Revision ID: editorial_indexed_cols_001
Revises: add_pool_tables_001
Create Date: 2026-04-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "editorial_indexed_cols_001"
down_revision: str | Sequence[str] | None = "add_pool_tables_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add columns
    op.add_column("asset_editorial", sa.Column("series_title", sa.String(512), nullable=True))
    op.add_column("asset_editorial", sa.Column("season_number", sa.Integer(), nullable=True))
    op.add_column("asset_editorial", sa.Column("episode_number", sa.Integer(), nullable=True))
    op.add_column("asset_editorial", sa.Column("content_rating", sa.String(32), nullable=True))
    op.add_column("asset_editorial", sa.Column("production_year", sa.Integer(), nullable=True))

    # 2. Create indexes
    op.create_index(
        "ix_asset_editorial_series_title_lower",
        "asset_editorial",
        [sa.text("lower(series_title)")],
    )
    op.create_index(
        "ix_asset_editorial_season_episode",
        "asset_editorial",
        ["season_number", "episode_number"],
    )
    op.create_index(
        "ix_asset_editorial_content_rating",
        "asset_editorial",
        ["content_rating"],
    )
    op.create_index(
        "ix_asset_editorial_production_year",
        "asset_editorial",
        ["production_year"],
    )

    # 3. Backfill from existing JSONB payload
    op.execute(sa.text("""
        UPDATE asset_editorial
        SET
            series_title = payload->>'series_title',
            season_number = CASE
                WHEN payload->>'season_number' IS NOT NULL
                    AND payload->>'season_number' ~ '^[0-9]+$'
                THEN (payload->>'season_number')::INTEGER
                ELSE NULL
            END,
            episode_number = CASE
                WHEN payload->>'episode_number' IS NOT NULL
                    AND payload->>'episode_number' ~ '^[0-9]+$'
                THEN (payload->>'episode_number')::INTEGER
                ELSE NULL
            END,
            content_rating = CASE
                WHEN jsonb_typeof(payload->'content_rating') = 'object'
                THEN payload->'content_rating'->>'code'
                ELSE payload->>'content_rating'
            END,
            production_year = CASE
                WHEN payload->>'production_year' IS NOT NULL
                    AND payload->>'production_year' ~ '^[0-9]+$'
                THEN (payload->>'production_year')::INTEGER
                WHEN payload->>'year' IS NOT NULL
                    AND payload->>'year' ~ '^[0-9]+$'
                THEN (payload->>'year')::INTEGER
                ELSE NULL
            END
        WHERE payload != '{}'::jsonb
    """))


def downgrade() -> None:
    op.drop_index("ix_asset_editorial_production_year", table_name="asset_editorial")
    op.drop_index("ix_asset_editorial_content_rating", table_name="asset_editorial")
    op.drop_index("ix_asset_editorial_season_episode", table_name="asset_editorial")
    op.drop_index("ix_asset_editorial_series_title_lower", table_name="asset_editorial")
    op.drop_column("asset_editorial", "production_year")
    op.drop_column("asset_editorial", "content_rating")
    op.drop_column("asset_editorial", "episode_number")
    op.drop_column("asset_editorial", "season_number")
    op.drop_column("asset_editorial", "series_title")
