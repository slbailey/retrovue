"""path_mapping: rename columns, add source_id FK, backfill

INV-PATH-MAPPING-SOURCE-SCOPED-001

Revision ID: pm_source_scoped_001
Revises: 00c766d4a2e0
Create Date: 2026-04-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pm_source_scoped_001"
down_revision: str | Sequence[str] | None = "20260315_containers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Rename columns: plex_path -> source_path, local_path -> retrovue_path
    op.alter_column("path_mappings", "plex_path", new_column_name="source_path")
    op.alter_column("path_mappings", "local_path", new_column_name="retrovue_path")

    # 2. Add source_id FK (nullable — existing rows are container-scoped)
    op.add_column(
        "path_mappings",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # 3. Make container_id nullable (source-level mappings have no container)
    op.alter_column("path_mappings", "container_id", nullable=True)

    # 4. Backfill source_id from container -> source relationship
    op.execute(
        """
        UPDATE path_mappings pm
        SET source_id = c.source_id
        FROM containers c
        WHERE pm.container_id = c.uuid
          AND pm.source_id IS NULL
        """
    )

    # 5. Add index on source_id
    op.create_index("ix_path_mappings_source_id", "path_mappings", ["source_id"])

    # 6. Add check constraint: at least one scope must be set
    op.create_check_constraint(
        "ck_path_mappings_scope",
        "path_mappings",
        "source_id IS NOT NULL OR container_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_path_mappings_scope", "path_mappings", type_="check")
    op.drop_index("ix_path_mappings_source_id", table_name="path_mappings")
    op.alter_column("path_mappings", "container_id", nullable=False)
    op.drop_column("path_mappings", "source_id")
    op.alter_column("path_mappings", "retrovue_path", new_column_name="local_path")
    op.alter_column("path_mappings", "source_path", new_column_name="plex_path")
