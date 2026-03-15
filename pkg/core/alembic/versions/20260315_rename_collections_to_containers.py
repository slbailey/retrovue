"""Phase 8: Rename collections → containers, collection_id/collection_uuid → container_id.

Final schema rename after application code has switched to Container/container_id.
Physical table and columns only; ORM already uses logical names.

Revision ID: 20260315_containers
Revises: 20260315_proc_out
Create Date: 2026-03-15

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260315_containers"
down_revision: str | Sequence[str] | None = "20260315_proc_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Rename table collections → containers ───────────────────────
    op.rename_table("collections", "containers")

    # Rename PK constraint and table-level constraints/indexes on containers
    op.execute("ALTER TABLE containers RENAME CONSTRAINT pk_collections TO pk_containers")
    op.execute(
        "ALTER TABLE containers RENAME CONSTRAINT uq_collections_source_external TO uq_containers_source_external"
    )
    op.execute(
        "ALTER TABLE containers RENAME CONSTRAINT fk_collections_source_id_sources TO fk_containers_source_id_sources"
    )
    op.execute("ALTER INDEX ix_collections_source_id RENAME TO ix_containers_source_id")
    op.execute("ALTER INDEX ix_collections_sync_enabled RENAME TO ix_containers_sync_enabled")
    op.execute("ALTER INDEX ix_collections_ingestible RENAME TO ix_containers_ingestible")

    # ── 2. assets: collection_uuid → container_id ──────────────────────
    op.alter_column(
        "assets",
        "collection_uuid",
        new_column_name="container_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
    )
    # FK: references containers(uuid)
    op.execute(
        "ALTER TABLE assets RENAME CONSTRAINT fk_assets_collection_uuid_collections TO fk_assets_container_id_containers"
    )
    # Unique constraints
    op.execute(
        "ALTER TABLE assets RENAME CONSTRAINT ix_assets_collection_canonical_unique TO ix_assets_container_canonical_unique"
    )
    op.execute(
        "ALTER TABLE assets RENAME CONSTRAINT ix_assets_collection_uri_unique TO ix_assets_container_uri_unique"
    )
    # uq_assets_source_container_locator name already uses "container"; no rename
    # Indexes
    op.execute("ALTER INDEX ix_assets_collection_uuid RENAME TO ix_assets_container_id")
    op.execute(
        "ALTER INDEX ix_assets_collection_canonical_uri RENAME TO ix_assets_container_canonical_uri"
    )
    # ix_assets_schedulable partial index: column is now container_id; index name left as-is

    # ── 3. path_mappings: collection_uuid → container_id ───────────────
    op.alter_column(
        "path_mappings",
        "collection_uuid",
        new_column_name="container_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
    )
    op.execute(
        "ALTER TABLE path_mappings RENAME CONSTRAINT fk_path_mappings_collection_uuid_collections TO fk_path_mappings_container_id_containers"
    )
    op.execute(
        "ALTER INDEX ix_path_mappings_collection_uuid RENAME TO ix_path_mappings_container_id"
    )

    # ── 4. schedule_items: collection_id → container_id ─────────────────
    op.alter_column(
        "schedule_items",
        "collection_id",
        new_column_name="container_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
    )


def downgrade() -> None:
    # ── 4. schedule_items: container_id → collection_id ───────────────
    op.alter_column(
        "schedule_items",
        "container_id",
        new_column_name="collection_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
    )

    # ── 3. path_mappings: container_id → collection_uuid ───────────────
    op.execute(
        "ALTER INDEX ix_path_mappings_container_id RENAME TO ix_path_mappings_collection_uuid"
    )
    op.execute(
        "ALTER TABLE path_mappings RENAME CONSTRAINT fk_path_mappings_container_id_containers TO fk_path_mappings_collection_uuid_collections"
    )
    op.alter_column(
        "path_mappings",
        "container_id",
        new_column_name="collection_uuid",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
    )

    # ── 2. assets: container_id → collection_uuid ─────────────────────
    op.execute(
        "ALTER TABLE assets RENAME CONSTRAINT ix_assets_container_uri_unique TO ix_assets_collection_uri_unique"
    )
    op.execute(
        "ALTER TABLE assets RENAME CONSTRAINT ix_assets_container_canonical_unique TO ix_assets_collection_canonical_unique"
    )
    op.execute(
        "ALTER TABLE assets RENAME CONSTRAINT fk_assets_container_id_containers TO fk_assets_collection_uuid_collections"
    )
    op.execute("ALTER INDEX ix_assets_container_canonical_uri RENAME TO ix_assets_collection_canonical_uri")
    op.execute("ALTER INDEX ix_assets_container_id RENAME TO ix_assets_collection_uuid")
    op.alter_column(
        "assets",
        "container_id",
        new_column_name="collection_uuid",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
    )

    # ── 1. Rename table containers → collections ───────────────────────
    op.execute("ALTER INDEX ix_containers_ingestible RENAME TO ix_collections_ingestible")
    op.execute("ALTER INDEX ix_containers_sync_enabled RENAME TO ix_collections_sync_enabled")
    op.execute("ALTER INDEX ix_containers_source_id RENAME TO ix_collections_source_id")
    op.execute(
        "ALTER TABLE containers RENAME CONSTRAINT fk_containers_source_id_sources TO fk_collections_source_id_sources"
    )
    op.execute(
        "ALTER TABLE containers RENAME CONSTRAINT uq_containers_source_external TO uq_collections_source_external"
    )
    op.execute("ALTER TABLE containers RENAME CONSTRAINT pk_containers TO pk_collections")
    op.rename_table("containers", "collections")
