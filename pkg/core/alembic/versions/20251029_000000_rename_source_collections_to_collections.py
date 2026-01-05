"""rename_source_collections_to_collections

Revision ID: a5c7b3f0c1d1
Revises: 9541bbc23bcd
Create Date: 2025-10-29 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5c7b3f0c1d1"
down_revision: str | Sequence[str] | None = "9541bbc23bcd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename the table
    op.rename_table('source_collections', 'collections')
    
    # Rename the primary key column from id to uuid
    op.alter_column('collections', 'id', new_column_name='uuid')
    
    # Rename indexes
    op.execute("ALTER INDEX ix_source_collections_ingestible RENAME TO ix_collections_ingestible")
    op.execute("ALTER INDEX ix_source_collections_source_id RENAME TO ix_collections_source_id")
    op.execute("ALTER INDEX ix_source_collections_sync_enabled RENAME TO ix_collections_sync_enabled")
    
    # Rename constraints
    op.execute("ALTER TABLE collections RENAME CONSTRAINT pk_source_collections TO pk_collections")
    op.execute("ALTER TABLE collections RENAME CONSTRAINT uq_source_collections_source_external TO uq_collections_source_external")
    op.execute("ALTER TABLE collections RENAME CONSTRAINT fk_source_collections_source_id_sources TO fk_collections_source_id_sources")
    
    # Update foreign key references in other tables
    op.execute("ALTER TABLE assets RENAME CONSTRAINT fk_assets_collection_uuid_source_collections TO fk_assets_collection_uuid_collections")
    op.execute("ALTER TABLE path_mappings RENAME CONSTRAINT fk_path_mappings_collection_id_source_collections TO fk_path_mappings_collection_id_collections")
    
    # Update foreign key column references to use uuid instead of id
    op.execute("ALTER TABLE assets DROP CONSTRAINT fk_assets_collection_uuid_collections")
    op.execute("ALTER TABLE assets ADD CONSTRAINT fk_assets_collection_uuid_collections FOREIGN KEY (collection_uuid) REFERENCES collections(uuid) ON DELETE RESTRICT")
    
    op.execute("ALTER TABLE path_mappings DROP CONSTRAINT fk_path_mappings_collection_id_collections")
    op.execute("ALTER TABLE path_mappings ADD CONSTRAINT fk_path_mappings_collection_id_collections FOREIGN KEY (collection_id) REFERENCES collections(uuid) ON DELETE CASCADE")


def downgrade() -> None:
    # Revert foreign key column references
    op.execute("ALTER TABLE assets DROP CONSTRAINT fk_assets_collection_uuid_collections")
    op.execute("ALTER TABLE assets ADD CONSTRAINT fk_assets_collection_uuid_source_collections FOREIGN KEY (collection_uuid) REFERENCES collections(uuid) ON DELETE SET NULL")
    
    op.execute("ALTER TABLE path_mappings DROP CONSTRAINT fk_path_mappings_collection_id_collections")
    op.execute("ALTER TABLE path_mappings ADD CONSTRAINT fk_path_mappings_collection_id_source_collections FOREIGN KEY (collection_id) REFERENCES collections(uuid) ON DELETE CASCADE")
    
    # Revert constraint names
    op.execute("ALTER TABLE collections RENAME CONSTRAINT pk_collections TO pk_source_collections")
    op.execute("ALTER TABLE collections RENAME CONSTRAINT uq_collections_source_external TO uq_source_collections_source_external")
    op.execute("ALTER TABLE collections RENAME CONSTRAINT fk_collections_source_id_sources TO fk_source_collections_source_id_sources")
    
    # Revert index names
    op.execute("ALTER INDEX ix_collections_ingestible RENAME TO ix_source_collections_ingestible")
    op.execute("ALTER INDEX ix_collections_source_id RENAME TO ix_source_collections_source_id")
    op.execute("ALTER INDEX ix_collections_sync_enabled RENAME TO ix_source_collections_sync_enabled")
    
    # Revert column name from uuid back to id
    op.alter_column('collections', 'uuid', new_column_name='id')
    
    # Revert table name
    op.rename_table('collections', 'source_collections')
