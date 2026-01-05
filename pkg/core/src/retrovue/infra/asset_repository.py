"""
Asset repository for database operations.

This module provides a thin wrapper around SQLAlchemy operations for Asset entities,
following the existing Unit of Work pattern used throughout the codebase.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.entities import Asset


class AssetRepository:
    """
    Repository for Asset database operations.

    Provides a clean interface for asset-related database operations while
    maintaining separation between domain logic and data access concerns.
    """

    def __init__(self, db: Session):
        """
        Initialize the repository with a database session.

        Args:
            db: SQLAlchemy session instance
        """
        self.db = db

    def get_by_collection_and_canonical_hash(
        self, collection_uuid: UUID, canonical_key_hash: str
    ) -> Asset | None:
        """
        Find an asset by collection UUID and canonical key hash.

        Uses scalar_one_or_none() to enforce the uniqueness constraint invariant.
        If more than one asset exists with the same canonical key hash in a collection
        (which should never happen due to the unique constraint), this will raise an
        exception during testing, helping surface data integrity issues.

        Args:
            collection_uuid: UUID of the collection
            canonical_key_hash: SHA256 hash of the canonical key

        Returns:
            Asset instance if found, None otherwise

        Raises:
            MultipleResultsFound: If more than one asset matches (data integrity issue)
        """
        stmt = select(Asset).where(
            Asset.collection_uuid == collection_uuid, Asset.canonical_key_hash == canonical_key_hash
        )
        return self.db.scalar_one_or_none(stmt)

    def exists_by_collection_and_canonical_hash(
        self, collection_uuid: UUID, canonical_key_hash: str
    ) -> bool:
        """
        Check if an asset exists by collection UUID and canonical key hash.

        Fast existence check that avoids loading the full row when only
        a boolean result is needed (e.g., for create vs update branching).

        Args:
            collection_uuid: UUID of the collection
            canonical_key_hash: SHA256 hash of the canonical key

        Returns:
            True if asset exists, False otherwise
        """
        stmt = (
            select(1)
            .where(
                Asset.collection_uuid == collection_uuid,
                Asset.canonical_key_hash == canonical_key_hash,
            )
            .limit(1)
        )
        return self.db.scalar(stmt) is not None

    def get_by_uuid(self, uuid: UUID) -> Asset | None:
        """
        Find an asset by its UUID.

        Args:
            uuid: UUID of the asset

        Returns:
            Asset instance if found, None otherwise
        """
        stmt = select(Asset).where(Asset.uuid == uuid)
        return self.db.scalar_one_or_none(stmt)

    def add(self, asset: Asset) -> None:
        """
        Add a new asset to the database.

        Args:
            asset: Asset instance to add
        """
        self.db.add(asset)

    def save(self, asset: Asset) -> None:
        """
        Save changes to an existing asset.

        This method is provided for consistency with repository patterns.
        In SQLAlchemy, changes to attached objects are automatically tracked
        and will be persisted when the session is committed.

        Args:
            asset: Asset instance to save
        """
        # SQLAlchemy automatically tracks changes to attached objects
        # No explicit save operation needed - changes are committed via UoW
        pass
