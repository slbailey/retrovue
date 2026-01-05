"""
Library service - single source of truth for content library operations.

This service provides all business operations for managing the content library.
CLI and API must use these services instead of direct database access.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from ..domain.entities import (
    Asset,
    EntityType,
    Episode,
    EpisodeAsset,
    ProviderRef,
    ReviewQueue,
    ReviewStatus,
)

logger = structlog.get_logger(__name__)


class LibraryService:
    """
    Authority for assets in the content library.

    This service is the single source of truth for all asset-related operations
    in the content library. It provides the authoritative interface for asset
    queries and mutations, ensuring data consistency and proper business logic
    enforcement.

    **Architectural Role:** Authority + Service/Capability Provider

    **Responsibilities:**
    - Register assets from discovery data
    - Enrich assets with metadata
    - Mark assets as canonical or non-canonical
    - Manage review queue operations
    - Handle asset soft/hard deletion and restoration
    - Provide asset queries and filtering

    **Critical Rule:** Do not bypass LibraryService to write Assets directly.
    All asset state changes must go through this service to maintain data
    integrity and enforce business rules.
    """

    def __init__(self, db: Session):
        """Initialize the library service with a database session."""
        self.db = db

    def register_asset_from_discovery(self, discovered: dict[str, Any]) -> Asset:
        """
        Register a new asset from discovery data.

        **Critical Safety Boundary:** New assets are registered with canonical=False by default.
        This ensures that discovered content is NOT immediately available to downstream
        schedulers and runtime systems. Assets must pass quality assurance and be
        explicitly approved before they can be used for broadcast.

        **Business Rule:** All newly discovered assets start in a pending state and
        must go through the approval process before becoming canonical.

        Args:
            discovered: Discovery data with keys:
                - path_uri: File path or URI
                - size: File size in bytes
                - hash_sha256: SHA-256 hash
                - provider: Provider name
                - raw_labels: Raw metadata labels
                - last_modified: Last modification timestamp

        Returns:
            The registered Asset entity (with canonical=False)
        """
        session = self.db

        try:
            # Extract discovery data
            path_uri = discovered["path_uri"]
            size = discovered["size"]
            hash_sha256 = discovered.get("hash_sha256")
            provider = discovered.get("provider", "filesystem")
            raw_labels = discovered.get("raw_labels", {})
            last_modified = discovered.get("last_modified")

            # Create new asset
            asset = Asset(
                uri=path_uri,
                size=size,
                hash_sha256=hash_sha256,
                discovered_at=datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                if last_modified
                else datetime.utcnow(),
                canonical=False,
            )

            session.add(asset)
            session.flush()  # Get the ID

            # Log the registration
            logger.info(
                "asset_registered",
                asset_id=str(asset.id),
                provider=provider,
                uri=path_uri,
                size=size,
                hash_sha256=hash_sha256,
                raw_labels=raw_labels,
            )

            # Always flush to realize PKs without committing
            session.flush()
            return asset

        except Exception as e:
            # Session rollback handled by get_db() dependency
            logger.error("asset_registration_failed", error=str(e), discovered=discovered)
            raise

    def enrich_asset(self, asset_id: int, enrichment: dict[str, Any]) -> Asset:
        """
        Enrich an asset with additional metadata.

        Args:
            asset_id: ID of the asset to enrich
            enrichment: Enrichment data with keys:
                - duration_ms: Duration in milliseconds
                - video_codec: Video codec
                - audio_codec: Audio codec
                - container: Container format

        Returns:
            The enriched Asset entity
        """
        session = self.db

        try:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise ValueError(f"Asset {asset_id} not found")

            # Apply enrichment data
            if "duration_ms" in enrichment:
                asset.duration_ms = enrichment["duration_ms"]
            if "video_codec" in enrichment:
                asset.video_codec = enrichment["video_codec"]
            if "audio_codec" in enrichment:
                asset.audio_codec = enrichment["audio_codec"]
            if "container" in enrichment:
                asset.container = enrichment["container"]

            # Log the enrichment
            logger.info("asset_enriched", asset_id=str(asset_id), enrichment=enrichment)

            # Always flush to get DB-generated values
            session.flush()
            return asset

        except Exception as e:
            # Session rollback handled by get_db() dependency
            logger.error(
                "asset_enrichment_failed",
                asset_id=str(asset_id),
                error=str(e),
                enrichment=enrichment,
            )
            raise

    def link_asset_to_episode(self, asset_id: int, episode_id: uuid.UUID) -> EpisodeAsset:
        """
        Link an asset to an episode.

        Args:
            asset_id: ID of the asset
            episode_id: ID of the episode

        Returns:
            The EpisodeAsset relationship
        """
        session = self.db

        try:
            # Verify asset exists
            asset = session.get(Asset, asset_id)
            if not asset:
                raise ValueError(f"Asset {asset_id} not found")

            # Verify episode exists
            episode = session.get(Episode, episode_id)
            if not episode:
                raise ValueError(f"Episode {episode_id} not found")

            # Create the relationship
            episode_asset = EpisodeAsset(episode_id=episode_id, asset_id=asset_id)

            session.add(episode_asset)

            # Log the linking
            logger.info("asset_linked", asset_id=str(asset_id), episode_id=str(episode_id))

            # Always flush to get DB-generated values
            session.flush()
            return episode_asset

        except Exception as e:
            # Session rollback handled by get_db() dependency
            logger.error(
                "asset_linking_failed",
                asset_id=str(asset_id),
                episode_id=str(episode_id),
                error=str(e),
            )
            raise

    def mark_asset_canonical(self, asset_id: int) -> Asset:
        """
        Mark an asset as canonical (approved for downstream schedulers and runtime).

        **Critical Safety Boundary:** This method marks an asset as approved for use by
        downstream schedulers and runtime systems. Once canonical=True, the asset is
        considered good enough for playout without human review.

        **Business Rule:** Only assets that have passed quality assurance and are
        deemed suitable for broadcast should be marked canonical. This is a safety
        boundary that prevents unapproved content from reaching the air.

        Args:
            asset_id: ID of the asset to mark as canonical

        Returns:
            The updated Asset entity with canonical=True
        """
        session = self.db

        try:
            asset = session.get(Asset, asset_id)
            if not asset:
                raise ValueError(f"Asset {asset_id} not found")

            asset.canonical = True

            # Log the canonicalization
            logger.info("asset_canonicalized", asset_id=str(asset_id))

            # Always flush to get DB-generated values
            session.flush()
            return asset

        except Exception as e:
            # Session rollback handled by get_db() dependency
            logger.error("asset_canonicalization_failed", asset_id=str(asset_id), error=str(e))
            raise

    def mark_asset_canonical_asset(self, asset: Asset) -> Asset:
        """
        Mark an asset as canonical (overloaded method).

        Args:
            asset: Asset to mark as canonical

        Returns:
            Updated asset
        """
        return self.mark_asset_canonical(asset.id)

    def enqueue_review(self, asset, reason: str, score: float) -> None:
        """
        Accepts either an Asset instance or a UUID asset_id.
        Enqueues a ReviewQueue row and commits.
        """
        asset_id = asset.id if hasattr(asset, "id") else asset
        if isinstance(asset_id, str):
            asset_id = UUID(asset_id)

        review = ReviewQueue(
            asset_id=asset_id,
            reason=reason,
            confidence=score,
            status=ReviewStatus.PENDING,
        )
        self.db.add(review)
        self.db.flush()

    # TODO: SCHEDULER WILL CALL HERE. Do not make the scheduler reach into lower layers.
    # If scheduler needs different filters, add methods here instead of querying the DB directly.
    def list_assets(
        self, status: Literal["pending", "canonical"] | None = None, include_deleted: bool = False
    ) -> list[Asset]:
        """
        List assets with optional status filter.

        Args:
            status: Optional status filter ('pending' or 'canonical')
            include_deleted: If True, include soft-deleted assets

        Returns:
            List of Asset entities
        """
        session = self.db

        try:
            query = session.query(Asset)

            # Exclude soft-deleted assets by default
            if not include_deleted:
                query = query.filter(Asset.is_deleted.is_(False))

            if status == "pending":
                # Assets that are not canonical
                query = query.filter(Asset.canonical.is_(False))
            elif status == "canonical":
                # Assets that are canonical
                query = query.filter(Asset.canonical.is_(True))

            assets = query.all()

            # Log the listing
            logger.info(
                "assets_listed", count=len(assets), status=status, include_deleted=include_deleted
            )

            return assets

        except Exception as e:
            logger.error("asset_listing_failed", error=str(e), status=status)
            raise

    def list_canonical_assets(
        self, query: str | None = None, include_deleted: bool = False
    ) -> list[Asset]:
        """
        List canonical assets with optional search filter.

        Args:
            query: Optional search query to filter by URI
            include_deleted: If True, include soft-deleted assets

        Returns:
            List of canonical Asset entities
        """
        session = self.db

        try:
            db_query = session.query(Asset).filter(Asset.canonical.is_(True))

            # Exclude soft-deleted assets by default
            if not include_deleted:
                db_query = db_query.filter(Asset.is_deleted.is_(False))

            if query:
                # Filter by URI containing the query string
                db_query = db_query.filter(Asset.uri.ilike(f"%{query}%"))

            # Order by discovered_at (most recent first)
            assets = db_query.order_by(Asset.discovered_at.desc()).all()

            # Log the listing
            logger.info(
                "canonical_assets_listed",
                count=len(assets),
                query=query,
                include_deleted=include_deleted,
            )

            return assets

        except Exception as e:
            logger.error("canonical_assets_listing_failed", error=str(e), query=query)
            raise

    def list_pending_assets(self) -> list[Asset]:
        """
        List pending assets (non-canonical).

        Returns:
            List of pending Asset entities
        """
        return self.list_assets(status="pending")

    def list_review_queue(self) -> list[ReviewQueue]:
        """
        List items in the review queue.

        Returns:
            List of ReviewQueue entities
        """
        session = self.db

        try:
            reviews = (
                session.query(ReviewQueue).filter(ReviewQueue.status == ReviewStatus.PENDING).all()
            )

            # Log the listing
            logger.info("review_queue_listed", count=len(reviews))

            return reviews

        except Exception as e:
            logger.error("review_queue_listing_failed", error=str(e))
            raise

    def resolve_review(self, review_id: UUID, episode_id: UUID, notes: str | None = None) -> bool:
        """
        Resolve a review queue item.

        Args:
            review_id: ID of the review to resolve
            episode_id: ID of the episode to associate
            notes: Optional resolution notes

        Returns:
            True if successful, False otherwise
        """
        session = self.db

        try:
            # Get the review
            review = session.get(ReviewQueue, review_id)
            if not review:
                logger.warning("review_not_found", review_id=str(review_id))
                return False

            # Update the review status
            review.status = ReviewStatus.RESOLVED
            review.resolved_at = datetime.utcnow()
            if notes:
                review.notes = notes

            # Link the asset to the episode
            self.link_asset_to_episode(review.asset_id, episode_id)

            # Log the resolution
            logger.info(
                "review_resolved",
                review_id=str(review_id),
                asset_id=str(review.asset_id),
                episode_id=str(episode_id),
                notes=notes,
            )

            # Always flush to get DB-generated values
            session.flush()
            return True

        except Exception as e:
            logger.error(
                "review_resolution_failed",
                review_id=str(review_id),
                episode_id=str(episode_id),
                error=str(e),
            )
            raise

    def list_assets_advanced(
        self,
        kind: str | None = None,
        series: str | None = None,
        season: int | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[Asset]:
        """
        List assets with advanced filtering options.

        Args:
            kind: Filter by asset kind (episode, ad, bumper, etc.)
            series: Filter by series title (case-insensitive)
            season: Filter by season number
            q: Search query for title or series_title (case-insensitive substring)
            limit: Maximum number of results
            offset: Number of results to skip
            include_deleted: If True, include soft-deleted assets

        Returns:
            List of Asset entities with stable ordering
        """
        session = self.db

        try:
            # Start with base query
            query = session.query(Asset)

            # Exclude soft-deleted assets by default
            if not include_deleted:
                query = query.filter(Asset.is_deleted.is_(False))

            # Join with ProviderRef to access series information
            query = query.join(ProviderRef, Asset.id == ProviderRef.asset_id)

            # Apply filters
            if kind:
                # Filter by kind in raw JSON data
                query = query.filter(ProviderRef.raw["kind"].astext == kind)

            if series:
                # Case-insensitive series title match
                query = query.filter(
                    ProviderRef.raw["grandparentTitle"].astext.ilike(f"%{series}%")
                )

            if season is not None:
                # Filter by season number
                query = query.filter(ProviderRef.raw["parentIndex"].astext == str(season))

            if q:
                # Search in title or series_title
                query = query.filter(
                    (ProviderRef.raw["title"].astext.ilike(f"%{q}%"))
                    | (ProviderRef.raw["grandparentTitle"].astext.ilike(f"%{q}%"))
                )

            # Apply pagination and ordering
            assets = (
                query.order_by(
                    ProviderRef.raw["grandparentTitle"].astext.asc().nulls_last(),
                    ProviderRef.raw["parentIndex"].astext.asc().nulls_last(),
                    ProviderRef.raw["index"].astext.asc().nulls_last(),
                    Asset.id.asc(),
                )
                .offset(offset)
                .limit(limit)
                .all()
            )

            logger.info(
                "assets_listed_advanced",
                count=len(assets),
                kind=kind,
                series=series,
                season=season,
                q=q,
            )
            return assets

        except Exception as e:
            logger.error(
                "assets_listing_advanced_failed",
                error=str(e),
                kind=kind,
                series=series,
                season=season,
                q=q,
            )
            raise

    def get_asset_by_id(self, asset_id: int, include_deleted: bool = False) -> Asset | None:
        """
        Get a single asset by ID.

        Args:
            asset_id: Asset identifier
            include_deleted: If True, include soft-deleted assets

        Returns:
            Asset entity or None if not found
        """
        session = self.db

        try:
            query = session.query(Asset).filter(Asset.id == asset_id)

            # Exclude soft-deleted assets by default
            if not include_deleted:
                query = query.filter(Asset.is_deleted.is_(False))

            asset = query.first()
            logger.info(
                "asset_retrieved",
                asset_id=str(asset_id),
                found=asset is not None,
                include_deleted=include_deleted,
            )
            return asset

        except Exception as e:
            logger.error("asset_retrieval_failed", asset_id=str(asset_id), error=str(e))
            raise

    def get_asset_by_uuid(self, asset_uuid: UUID, include_deleted: bool = False) -> Asset | None:
        """
        Get a single asset by UUID.

        Args:
            asset_uuid: Asset UUID
            include_deleted: If True, include soft-deleted assets

        Returns:
            Asset entity or None if not found
        """
        session = self.db

        try:
            query = session.query(Asset).filter(Asset.uuid == asset_uuid)

            # Exclude soft-deleted assets by default
            if not include_deleted:
                query = query.filter(Asset.is_deleted.is_(False))

            asset = query.first()
            logger.info(
                "asset_retrieved_by_uuid",
                asset_uuid=str(asset_uuid),
                found=asset is not None,
                include_deleted=include_deleted,
            )
            return asset

        except Exception as e:
            logger.error("asset_retrieval_by_uuid_failed", asset_uuid=str(asset_uuid), error=str(e))
            raise

    def get_asset_by_source_rating_key(self, rating_key: str) -> Asset | None:
        """
        Get asset by source rating key.

        Args:
            rating_key: Source rating key (e.g., Plex rating key)

        Returns:
            Asset entity or None if not found
        """
        session = self.db

        try:
            # Find ProviderRef with matching provider_key
            provider_ref = (
                session.query(ProviderRef)
                .filter(
                    ProviderRef.provider_key == rating_key,
                    ProviderRef.entity_type == EntityType.ASSET,
                )
                .first()
            )

            if not provider_ref:
                logger.info("asset_not_found_by_rating_key", rating_key=rating_key)
                return None

            asset = session.get(Asset, provider_ref.entity_id)
            logger.info(
                "asset_retrieved_by_rating_key",
                rating_key=rating_key,
                asset_id=str(asset.id) if asset else None,
            )
            return asset

        except Exception as e:
            logger.error(
                "asset_retrieval_by_rating_key_failed", rating_key=rating_key, error=str(e)
            )
            raise

    def list_series(self, distinct_only: bool = True) -> list[str]:
        """
        List distinct series titles from assets.

        Args:
            distinct_only: If True, return only distinct series names

        Returns:
            List of series titles, ordered case-insensitive
        """
        session = self.db

        try:
            # Get all series titles first, then deduplicate and sort in Python
            query = session.query(ProviderRef.raw["grandparentTitle"].astext).filter(
                ProviderRef.raw["grandparentTitle"].astext.isnot(None),
                ProviderRef.entity_type == EntityType.ASSET,
            )

            all_series = [row[0] for row in query.all()]

            if distinct_only:
                # Remove duplicates while preserving order
                seen = set()
                series_titles = []
                for series in all_series:
                    if series not in seen:
                        seen.add(series)
                        series_titles.append(series)
            else:
                series_titles = all_series

            # Sort case-insensitive
            series_titles.sort(key=str.lower)

            logger.info("series_listed", count=len(series_titles), distinct_only=distinct_only)
            return series_titles

        except Exception as e:
            logger.error("series_listing_failed", error=str(e), distinct_only=distinct_only)
            raise

    def list_episodes_by_series(self, series: str) -> list[Asset]:
        """
        List all episode assets for a specific series.

        Args:
            series: Series title (case-insensitive exact match)

        Returns:
            List of Asset entities ordered by season_number, episode_number
        """
        session = self.db

        try:
            # Join Asset with ProviderRef to access series information
            query = (
                session.query(Asset)
                .join(ProviderRef, Asset.id == ProviderRef.asset_id)
                .filter(
                    ProviderRef.raw["grandparentTitle"].astext.ilike(f"%{series}%"),
                    ProviderRef.entity_type == EntityType.ASSET,
                )
            )

            # Order by season and episode
            assets = query.order_by(
                ProviderRef.raw["parentIndex"].astext.asc().nulls_last(),
                ProviderRef.raw["index"].astext.asc().nulls_last(),
            ).all()

            logger.info("episodes_listed_by_series", series=series, count=len(assets))
            return assets

        except Exception as e:
            logger.error("episodes_listing_by_series_failed", series=series, error=str(e))
            raise

    def soft_delete_asset_by_uuid(
        self, asset_uuid: UUID, deleted_at: datetime | None = None
    ) -> bool:
        """
        Soft delete an asset by UUID.

        Args:
            asset_uuid: Asset UUID to soft delete
            deleted_at: Optional deletion timestamp (defaults to now)

        Returns:
            True if asset was found and updated, False otherwise
        """
        session = self.db

        try:
            if deleted_at is None:
                deleted_at = datetime.utcnow()

            # Find asset by UUID
            asset = session.query(Asset).filter(Asset.uuid == asset_uuid).first()
            if not asset:
                logger.info("asset_not_found_for_soft_delete", asset_uuid=str(asset_uuid))
                return False

            # Check if already soft deleted
            if asset.is_deleted:
                logger.info("asset_already_soft_deleted", asset_uuid=str(asset_uuid))
                return True

            # Perform soft delete
            asset.is_deleted = True
            asset.deleted_at = deleted_at

            session.flush()

            logger.info("asset_soft_deleted", asset_uuid=str(asset_uuid), asset_id=str(asset.id))
            return True

        except Exception as e:
            logger.error("asset_soft_delete_failed", asset_uuid=str(asset_uuid), error=str(e))
            raise

    def soft_delete_asset_by_id(self, asset_id: UUID, deleted_at: datetime | None = None) -> bool:
        """
        Soft delete an asset by ID.

        Args:
            asset_id: Asset ID to soft delete
            deleted_at: Optional deletion timestamp (defaults to now)

        Returns:
            True if asset was found and updated, False otherwise
        """
        session = self.db

        try:
            if deleted_at is None:
                deleted_at = datetime.utcnow()

            # Find asset by ID
            asset = session.get(Asset, asset_id)
            if not asset:
                logger.info("asset_not_found_for_soft_delete", asset_id=str(asset_id))
                return False

            # Check if already soft deleted
            if asset.is_deleted:
                logger.info("asset_already_soft_deleted", asset_id=str(asset_id))
                return True

            # Perform soft delete
            asset.is_deleted = True
            asset.deleted_at = deleted_at

            session.flush()

            logger.info("asset_soft_deleted", asset_id=str(asset_id))
            return True

        except Exception as e:
            logger.error("asset_soft_delete_failed", asset_id=str(asset_id), error=str(e))
            raise

    def soft_delete_asset_by_source_rating_key(
        self, rating_key: str, deleted_at: datetime | None = None
    ) -> bool:
        """
        Soft delete an asset by source rating key.

        Args:
            rating_key: Source rating key (e.g., Plex rating key)
            deleted_at: Optional deletion timestamp (defaults to now)

        Returns:
            True if asset was found and updated, False otherwise
        """
        session = self.db

        try:
            if deleted_at is None:
                deleted_at = datetime.utcnow()

            # Find asset by rating key
            asset = self.get_asset_by_source_rating_key(rating_key)
            if not asset:
                logger.info("asset_not_found_for_soft_delete_by_rating_key", rating_key=rating_key)
                return False

            # Check if already soft deleted
            if asset.is_deleted:
                logger.info("asset_already_soft_deleted_by_rating_key", rating_key=rating_key)
                return True

            # Perform soft delete
            asset.is_deleted = True
            asset.deleted_at = deleted_at

            session.flush()

            logger.info(
                "asset_soft_deleted_by_rating_key", rating_key=rating_key, asset_id=str(asset.id)
            )
            return True

        except Exception as e:
            logger.error(
                "asset_soft_delete_by_rating_key_failed", rating_key=rating_key, error=str(e)
            )
            raise

    def is_asset_referenced_by_episodes(self, asset_id: int) -> bool:
        """
        Check if an asset is referenced by any episodes.

        Args:
            asset_id: Asset ID to check

        Returns:
            True if asset is referenced by episodes, False otherwise
        """
        session = self.db

        try:
            # Check episode_assets junction table
            count = session.query(EpisodeAsset).filter(EpisodeAsset.asset_id == asset_id).count()

            logger.info(
                "asset_reference_check", asset_id=str(asset_id), referenced=count > 0, count=count
            )
            return count > 0

        except Exception as e:
            logger.error("asset_reference_check_failed", asset_id=str(asset_id), error=str(e))
            raise

    def hard_delete_asset_by_uuid(self, asset_uuid: UUID, force: bool = False) -> bool:
        """
        Hard delete an asset by UUID.

        Args:
            asset_uuid: Asset UUID to hard delete
            force: If True, delete even if referenced by episodes

        Returns:
            True if asset was found and deleted, False otherwise

        Raises:
            ValueError: If asset is referenced and force=False
        """
        session = self.db

        try:
            # Find asset by UUID
            asset = session.query(Asset).filter(Asset.uuid == asset_uuid).first()
            if not asset:
                logger.info("asset_not_found_for_hard_delete", asset_uuid=str(asset_uuid))
                return False

            # Check if referenced by episodes
            if not force and self.is_asset_referenced_by_episodes(asset.id):
                raise ValueError(
                    f"Asset {asset_uuid} is referenced by episodes. Use force=True to override."
                )

            # Delete the asset (CASCADE will handle related records)
            session.delete(asset)
            session.flush()

            logger.info("asset_hard_deleted", asset_uuid=str(asset_uuid), asset_id=str(asset.id))
            return True

        except ValueError:
            raise
        except Exception as e:
            logger.error("asset_hard_delete_failed", asset_uuid=str(asset_uuid), error=str(e))
            raise

    def restore_asset_by_uuid(self, asset_uuid: UUID) -> bool:
        """
        Restore a soft-deleted asset by UUID.

        Args:
            asset_uuid: Asset UUID to restore

        Returns:
            True if asset was found and restored, False otherwise
        """
        session = self.db

        try:
            # Find asset by UUID
            asset = session.query(Asset).filter(Asset.uuid == asset_uuid).first()
            if not asset:
                logger.info("asset_not_found_for_restore", asset_uuid=str(asset_uuid))
                return False

            # Check if not soft deleted
            if not asset.is_deleted:
                logger.info("asset_not_soft_deleted", asset_uuid=str(asset_uuid))
                return False

            # Restore the asset
            asset.is_deleted = False
            asset.deleted_at = None

            session.flush()

            logger.info("asset_restored", asset_uuid=str(asset_uuid), asset_id=str(asset.id))
            return True

        except Exception as e:
            logger.error("asset_restore_failed", asset_uuid=str(asset_uuid), error=str(e))
            raise
