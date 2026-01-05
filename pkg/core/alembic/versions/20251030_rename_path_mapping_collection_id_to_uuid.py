"""rename_path_mapping_collection_id_to_uuid

Revision ID: b1c2d3e4f5a6
Revises: a5c7b3f0c1d2
Create Date: 2025-10-30 12:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a5c7b3f0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename column collection_id -> collection_uuid
    with op.batch_alter_table("path_mappings") as batch_op:
        batch_op.alter_column("collection_id", new_column_name="collection_uuid")

    # Update index name if exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes WHERE indexname = 'ix_path_mappings_collection_id'
            ) THEN
                ALTER INDEX ix_path_mappings_collection_id RENAME TO ix_path_mappings_collection_uuid;
            END IF;
        END$$;
    """)

    # Update FK constraint name if needed
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints 
                WHERE constraint_name = 'fk_path_mappings_collection_id_collections'
            ) THEN
                ALTER TABLE path_mappings RENAME CONSTRAINT fk_path_mappings_collection_id_collections TO fk_path_mappings_collection_uuid_collections;
            END IF;
        END$$;
    """)


def downgrade() -> None:
    # Revert FK and index names
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_indexes WHERE indexname = 'ix_path_mappings_collection_uuid'
            ) THEN
                ALTER INDEX ix_path_mappings_collection_uuid RENAME TO ix_path_mappings_collection_id;
            END IF;
        END$$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.table_constraints 
                WHERE constraint_name = 'fk_path_mappings_collection_uuid_collections'
            ) THEN
                ALTER TABLE path_mappings RENAME CONSTRAINT fk_path_mappings_collection_uuid_collections TO fk_path_mappings_collection_id_collections;
            END IF;
        END$$;
    """)

    with op.batch_alter_table("path_mappings") as batch_op:
        batch_op.alter_column("collection_uuid", new_column_name="collection_id")










