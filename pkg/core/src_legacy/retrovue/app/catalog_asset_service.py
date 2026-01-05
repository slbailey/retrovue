"""
CatalogAssetService - Service for managing broadcast-approved catalog assets.

This service handles canonical (approved-for-air) assets that are ready for scheduling.
It provides UUID-based access to catalog assets and enforces business rules for
asset management in the broadcast domain.
"""

import uuid
from typing import Any

from sqlalchemy import select

from ..infra.uow import session
from ..schedule_manager.models import CatalogAsset


class CatalogAssetService:
    """
    Service class for CatalogAsset operations and business logic.

    This service handles canonical assets that are approved for broadcast scheduling.
    All database access goes through SQLAlchemy sessions with proper transaction handling.
    """

    @staticmethod
    def get_asset_by_uuid(asset_uuid: uuid.UUID) -> dict[str, Any] | None:
        """
        Return full details for one CatalogAsset by UUID.

        Args:
            asset_uuid: The UUID of the asset to retrieve

        Returns:
            Dict with all asset fields using UUID as external identity, or None if not found
        """
        with session() as db:
            asset = db.execute(
                select(CatalogAsset).where(CatalogAsset.uuid == asset_uuid)
            ).scalar_one_or_none()

            if not asset:
                return None

            return {
                "uuid": str(asset.uuid),
                "title": asset.title,
                "duration_ms": asset.duration_ms,
                "tags": asset.tags,
                "canonical": asset.canonical,
                "file_path": asset.file_path,
                "source_ingest_asset_id": asset.source_ingest_asset_id,
                "created_at": asset.created_at.isoformat(),
            }

    @staticmethod
    def list_canonical_assets() -> list[dict[str, Any]]:
        """
        Return a list of all canonical (approved-for-air) CatalogAssets.

        Returns:
            List of dicts with: uuid, title, duration_ms, tags, canonical, file_path,
            source_ingest_asset_id, created_at
        """
        with session() as db:
            assets = db.execute(select(CatalogAsset).where(CatalogAsset.canonical)).scalars().all()

            result = []
            for asset in assets:
                result.append(
                    {
                        "uuid": str(asset.uuid),
                        "title": asset.title,
                        "duration_ms": asset.duration_ms,
                        "tags": asset.tags,
                        "canonical": asset.canonical,
                        "file_path": asset.file_path,
                        "source_ingest_asset_id": asset.source_ingest_asset_id,
                        "created_at": asset.created_at.isoformat(),
                    }
                )

            return result

    @staticmethod
    def list_all_assets() -> list[dict[str, Any]]:
        """
        Return a list of all CatalogAssets (both canonical and non-canonical).

        Returns:
            List of dicts with: uuid, title, duration_ms, tags, canonical, file_path,
            source_ingest_asset_id, created_at
        """
        with session() as db:
            assets = db.execute(select(CatalogAsset)).scalars().all()

            result = []
            for asset in assets:
                result.append(
                    {
                        "uuid": str(asset.uuid),
                        "title": asset.title,
                        "duration_ms": asset.duration_ms,
                        "tags": asset.tags,
                        "canonical": asset.canonical,
                        "file_path": asset.file_path,
                        "source_ingest_asset_id": asset.source_ingest_asset_id,
                        "created_at": asset.created_at.isoformat(),
                    }
                )

            return result
