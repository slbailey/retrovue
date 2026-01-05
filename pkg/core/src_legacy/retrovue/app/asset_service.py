"""
AssetService - Service for managing ingest/library assets.

This service handles media assets in the library domain, including their metadata,
review status, and lifecycle management. It provides UUID-based access to assets
and supports both internal operations and external integrations.
"""

import uuid
from typing import Any

from sqlalchemy import select

from ..domain.entities import Asset, Marker, ReviewQueue
from ..infra.uow import session


class AssetService:
    """
    Service class for Asset operations and business logic.

    This service handles media assets in the library domain, including metadata,
    review queues, and markers. All database access goes through SQLAlchemy sessions
    with proper transaction handling.
    """

    @staticmethod
    def get_asset_by_uuid(asset_uuid: uuid.UUID) -> dict[str, Any] | None:
        """
        Return full details for one Asset by UUID.

        Args:
            asset_uuid: The UUID of the asset to retrieve

        Returns:
            Dict with all asset fields using UUID as external identity, or None if not found
        """
        with session() as db:
            asset = db.execute(select(Asset).where(Asset.uuid == asset_uuid)).scalar_one_or_none()

            if not asset:
                return None

            # Get review queue summary
            review_items = (
                db.execute(select(ReviewQueue).where(ReviewQueue.asset_id == asset.id))
                .scalars()
                .all()
            )

            review_summary = {
                "total_items": len(review_items),
                "pending_items": len(
                    [item for item in review_items if item.status.value == "PENDING"]
                ),
                "resolved_items": len(
                    [item for item in review_items if item.status.value == "RESOLVED"]
                ),
            }

            # Get markers summary
            markers = db.execute(select(Marker).where(Marker.asset_id == asset.id)).scalars().all()

            markers_summary = {
                "total_markers": len(markers),
                "marker_types": list(set([marker.kind.value for marker in markers])),
            }

            return {
                "uuid": str(asset.uuid),
                "uri": asset.uri,
                "size": asset.size,
                "duration_ms": asset.duration_ms,
                "video_codec": asset.video_codec,
                "audio_codec": asset.audio_codec,
                "container": asset.container,
                "hash_sha256": asset.hash_sha256,
                "canonical": asset.canonical,
                "is_deleted": asset.is_deleted,
                "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
                "discovered_at": asset.discovered_at.isoformat(),
                "review_summary": review_summary,
                "markers_summary": markers_summary,
            }

    @staticmethod
    def list_assets() -> list[dict[str, Any]]:
        """
        Return a list of all Assets (excluding deleted ones by default).

        Returns:
            List of dicts with: uuid, uri, size, duration_ms, canonical, is_deleted,
            deleted_at, discovered_at
        """
        with session() as db:
            assets = db.execute(select(Asset).where(not Asset.is_deleted)).scalars().all()

            result = []
            for asset in assets:
                result.append(
                    {
                        "uuid": str(asset.uuid),
                        "uri": asset.uri,
                        "size": asset.size,
                        "duration_ms": asset.duration_ms,
                        "canonical": asset.canonical,
                        "is_deleted": asset.is_deleted,
                        "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
                        "discovered_at": asset.discovered_at.isoformat(),
                    }
                )

            return result

    @staticmethod
    def list_canonical_assets() -> list[dict[str, Any]]:
        """
        Return a list of all canonical (approved) Assets.

        Returns:
            List of dicts with: uuid, uri, size, duration_ms, canonical, is_deleted,
            deleted_at, discovered_at
        """
        with session() as db:
            assets = (
                db.execute(select(Asset).where(Asset.canonical, not Asset.is_deleted))
                .scalars()
                .all()
            )

            result = []
            for asset in assets:
                result.append(
                    {
                        "uuid": str(asset.uuid),
                        "uri": asset.uri,
                        "size": asset.size,
                        "duration_ms": asset.duration_ms,
                        "canonical": asset.canonical,
                        "is_deleted": asset.is_deleted,
                        "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
                        "discovered_at": asset.discovered_at.isoformat(),
                    }
                )

            return result

    @staticmethod
    def list_deleted_assets() -> list[dict[str, Any]]:
        """
        Return a list of all deleted Assets.

        Returns:
            List of dicts with: uuid, uri, size, duration_ms, canonical, is_deleted,
            deleted_at, discovered_at
        """
        with session() as db:
            assets = db.execute(select(Asset).where(Asset.is_deleted)).scalars().all()

            result = []
            for asset in assets:
                result.append(
                    {
                        "uuid": str(asset.uuid),
                        "uri": asset.uri,
                        "size": asset.size,
                        "duration_ms": asset.duration_ms,
                        "canonical": asset.canonical,
                        "is_deleted": asset.is_deleted,
                        "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
                        "discovered_at": asset.discovered_at.isoformat(),
                    }
                )

            return result
