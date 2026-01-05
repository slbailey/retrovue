"""
Assets API endpoints.

This module provides REST API endpoints for managing assets and review queue.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from src_legacy.retrovue.content_manager.library_service import LibraryService

from ...api.schemas import (
    AssetDetailResponse,
    AssetListResponse,
    AssetSummary,
    AssetWithReviews,
    EpisodesBySeriesResponse,
    EpisodeSummary,
    ReviewQueueListResponse,
    ReviewQueueSummary,
    SeriesListResponse,
)
from ...domain.entities import Asset, ReviewQueue
from ...infra.uow import get_db

router = APIRouter(prefix="/api/v1", tags=["assets"])


@router.get("/assets", response_model=AssetListResponse)
async def list_assets(
    status: Literal["pending", "canonical"] | None = Query(
        None, description="Filter by asset status"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of assets to return"),
    offset: int = Query(0, ge=0, description="Number of assets to skip"),
    db: Session = Depends(get_db),
) -> AssetListResponse:
    """
    List assets with optional filtering.

    Args:
        status: Optional status filter ('pending' or 'canonical')
        limit: Maximum number of assets to return
        offset: Number of assets to skip

    Returns:
        List of assets with metadata
    """
    try:
        library_service = LibraryService(db)
        assets = library_service.list_assets(status=status, include_deleted=False)

        # Apply pagination
        total = len(assets)
        paginated_assets = assets[offset : offset + limit]

        # Convert to DTOs
        asset_summaries = [AssetSummary.from_orm(asset) for asset in paginated_assets]

        return AssetListResponse(assets=asset_summaries, total=total, status_filter=status)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list assets: {str(e)}",
        )


@router.get("/assets/{asset_uuid}", response_model=AssetDetailResponse)
async def get_asset(
    asset_uuid: UUID,
    db: Session = Depends(get_db),
) -> AssetDetailResponse:
    """
    Get detailed information about a specific asset.

    Args:
        asset_id: Asset identifier

    Returns:
        Detailed asset information with reviews
    """
    try:
        # Get asset from database (exclude soft-deleted by default)
        asset = (
            db.query(Asset).filter(Asset.uuid == asset_uuid, Asset.is_deleted.is_(False)).first()
        )
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {asset_uuid} not found"
            )

        # Create response with counts
        asset_with_reviews = AssetWithReviews.from_orm(asset)

        return AssetDetailResponse(
            asset=asset_with_reviews,
            episode_count=len(asset.episodes),
            marker_count=len(asset.markers),
            provider_ref_count=len(asset.provider_refs),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get asset: {str(e)}",
        )


@router.get("/review-queue", response_model=ReviewQueueListResponse)
async def list_review_queue(
    status: Literal["pending", "resolved"] | None = Query(
        None, description="Filter by review status"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of reviews to return"),
    offset: int = Query(0, ge=0, description="Number of reviews to skip"),
    db: Session = Depends(get_db),
) -> ReviewQueueListResponse:
    """
    List review queue items with optional filtering.

    Args:
        status: Optional status filter ('pending' or 'resolved')
        limit: Maximum number of reviews to return
        offset: Number of reviews to skip

    Returns:
        List of review queue items with metadata
    """
    try:
        query = db.query(ReviewQueue)

        if status == "pending":
            from ...shared.types import ReviewStatus

            query = query.filter(ReviewQueue.status == ReviewStatus.PENDING)
        elif status == "resolved":
            from ...shared.types import ReviewStatus

            query = query.filter(ReviewQueue.status == ReviewStatus.RESOLVED)

        # Get total count
        total = query.count()

        # Apply pagination
        reviews = query.offset(offset).limit(limit).all()

        # Convert to DTOs
        review_summaries = [ReviewQueueSummary.from_orm(review) for review in reviews]

        return ReviewQueueListResponse(reviews=review_summaries, total=total, status_filter=status)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list review queue: {str(e)}",
        )


@router.post("/assets/{asset_uuid}/enqueue-review")
async def enqueue_asset_review(
    asset_uuid: UUID,
    reason: str,
    confidence: float = 0.5,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """
    Enqueue an asset for review.

    Args:
        asset_id: Asset identifier
        reason: Reason for review
        confidence: Confidence score (0.0-1.0)

    Returns:
        Success status
    """
    try:
        library_service = LibraryService(db)
        # Find asset by UUID first
        asset = library_service.get_asset_by_uuid(asset_uuid)
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {asset_uuid} not found"
            )
        library_service.enqueue_review(asset.id, reason, confidence)

        return {"success": True}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue review: {str(e)}",
        )


@router.get("/assets/advanced", response_model=AssetListResponse)
async def list_assets_advanced(
    kind: str | None = Query(None, description="Filter by asset kind"),
    series: str | None = Query(None, description="Filter by series title"),
    season: int | None = Query(None, description="Filter by season number"),
    q: str | None = Query(None, description="Search query for title or series"),
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of assets to return"),
    offset: int = Query(0, ge=0, description="Number of assets to skip"),
    db: Session = Depends(get_db),
) -> AssetListResponse:
    """
    List assets with advanced filtering options.

    Args:
        kind: Filter by asset kind (episode, ad, bumper, etc.)
        series: Filter by series title (case-insensitive)
        season: Filter by season number
        q: Search query for title or series_title (case-insensitive substring)
        limit: Maximum number of assets to return
        offset: Number of assets to skip

    Returns:
        List of assets with metadata
    """
    try:
        library_service = LibraryService(db)
        assets = library_service.list_assets_advanced(
            kind=kind, series=series, season=season, q=q, limit=limit, offset=offset
        )

        # Convert to DTOs
        asset_summaries = [AssetSummary.from_orm(asset) for asset in assets]

        return AssetListResponse(assets=asset_summaries, total=len(asset_summaries))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list assets: {str(e)}",
        )


@router.get("/series", response_model=SeriesListResponse)
async def list_series(
    q: str | None = Query(None, description="Filter series names by substring"),
    db: Session = Depends(get_db),
) -> SeriesListResponse:
    """
    List all series titles.

    Args:
        q: Optional substring filter for series names

    Returns:
        List of distinct series titles
    """
    try:
        library_service = LibraryService(db)
        series_list = library_service.list_series()

        # Apply substring filter if provided
        if q:
            series_list = [s for s in series_list if q.lower() in s.lower()]

        return SeriesListResponse(series=series_list)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list series: {str(e)}",
        )


@router.get("/series/{series}/episodes", response_model=EpisodesBySeriesResponse)
async def list_episodes_by_series(
    series: str,
    season: int | None = Query(None, description="Filter by season number"),
    db: Session = Depends(get_db),
) -> EpisodesBySeriesResponse:
    """
    List episodes for a specific series.

    Args:
        series: Series title (case-insensitive)
        season: Optional season filter

    Returns:
        List of episodes for the series, ordered by season and episode
    """
    try:
        library_service = LibraryService(db)
        assets = library_service.list_episodes_by_series(series)

        if not assets:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Series '{series}' not found"
            )

        # Convert to episode summaries
        episodes = []
        for asset in assets:
            # Get series info from ProviderRef
            from ...domain.entities import ProviderRef

            provider_ref = db.query(ProviderRef).filter(ProviderRef.asset_id == asset.id).first()

            if provider_ref and provider_ref.raw:
                raw = provider_ref.raw

                # Apply season filter if provided
                if season is not None and int(raw.get("parentIndex", 0)) != season:
                    continue

                episode = EpisodeSummary(
                    id=asset.id,
                    uuid=asset.uuid,
                    title=raw.get("title", ""),
                    series_title=raw.get("grandparentTitle", series),
                    season_number=int(raw.get("parentIndex", 0)),
                    episode_number=int(raw.get("index", 0)),
                    duration_sec=asset.duration_ms // 1000 if asset.duration_ms else None,
                    kind=raw.get("kind", "episode"),
                    source=raw.get("source", "plex"),
                    source_rating_key=raw.get("ratingKey", ""),
                )
                episodes.append(episode)

        return EpisodesBySeriesResponse(series=series, episodes=episodes, total=len(episodes))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list episodes for series: {str(e)}",
        )


@router.delete("/assets/{asset_uuid}")
async def delete_asset(
    asset_uuid: UUID,
    hard: bool = Query(False, description="Perform hard delete (permanent removal)"),
    force: bool = Query(False, description="Force hard delete even if referenced"),
    dry_run: bool = Query(False, description="Show what would happen without making changes"),
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    """
    Delete an asset (soft delete by default, hard delete with hard=true).

    Args:
        asset_uuid: Asset UUID to delete
        hard: If True, perform hard delete (permanent removal)
        force: If True, force hard delete even if referenced by episodes
        dry_run: If True, show what would happen without making changes

    Returns:
        JSON response with action details
    """
    try:
        library_service = LibraryService(db)

        # Find asset
        asset = library_service.get_asset_by_id(asset_uuid, include_deleted=True)
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {asset_uuid} not found"
            )

        # Check if already soft deleted (for soft delete)
        if not hard and asset.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Asset is already soft-deleted"
            )

        # Check references for hard delete
        referenced = False
        if hard:
            referenced = library_service.is_asset_referenced_by_episodes(asset.id)

        # Prepare result data
        result = {
            "action": "hard_delete" if hard else "soft_delete",
            "uuid": str(asset.uuid),
            "id": str(asset.id),
            "referenced": referenced,
        }

        # Dry run mode
        if dry_run:
            return result

        # Check for conflicts
        if hard and not force and referenced:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Asset is referenced by episodes. Use force=true to override or perform a soft delete.",
            )

        # Perform deletion
        if hard:
            success = library_service.hard_delete_asset_by_uuid(asset.uuid, force=force)
        else:
            success = library_service.soft_delete_asset_by_uuid(asset.uuid)

        if success:
            result["status"] = "ok"
            return result
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete asset"
            )

    except HTTPException:
        raise
    except ValueError as e:
        if "referenced by episodes" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        else:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete asset: {str(e)}",
        )


@router.post("/assets/{asset_uuid}/restore")
async def restore_asset(
    asset_uuid: UUID,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """
    Restore a soft-deleted asset.

    Args:
        asset_uuid: Asset UUID to restore

    Returns:
        JSON response with status
    """
    try:
        library_service = LibraryService(db)

        # Find asset
        asset = library_service.get_asset_by_id(asset_uuid, include_deleted=True)
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {asset_uuid} not found"
            )

        # Check if not soft deleted
        if not asset.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Asset is not soft-deleted"
            )

        # Perform restore
        success = library_service.restore_asset_by_uuid(asset_uuid)

        if success:
            return {"action": "restore", "uuid": str(asset_uuid), "status": "ok"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to restore asset"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore asset: {str(e)}",
        )
