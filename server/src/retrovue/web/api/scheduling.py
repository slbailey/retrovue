"""
REST API endpoints for schedule management.

Provides a frontend-agnostic JSON API that can be consumed by HTMX templates,
React/Vue SPAs, or any other HTTP client.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...domain.entities import Asset, AssetEditorial
from ...infra.uow import session as get_session
from ...runtime.clock import AuthoritativeClock
from ...usecases.schedule_revision_lifecycle import (
    create_draft_revision,
    get_revision,
    list_revisions,
    publish_revision,
    ChannelNotFoundError,
    RevisionEmptyError,
    RevisionNotDraftError,
    RevisionNotFoundError,
)
from ._clock import get_clock

router = APIRouter(prefix="/api/scheduling", tags=["scheduling"])


# Dependency to get database session
def get_db():
    """Get database session for dependency injection."""
    db = get_session()
    try:
        with db as session:
            yield session
    finally:
        pass


# ============================================================================
# Pydantic Models for Request/Response
# ============================================================================


class AssetSummary(BaseModel):
    """Summary model for assets in content browser."""
    uuid: str
    uri: str
    duration_ms: int | None
    content_class: str | None
    daypart_profile: str | None
    genres: list[str] | None
    title: str | None


# ============================================================================
# Assets Browser Endpoint
# ============================================================================


@router.get("/assets")
async def list_assets(
    content_class: str | None = Query(None, description="Filter by content class (cartoon, sitcom, movie, etc.)"),
    daypart_profile: str | None = Query(None, description="Filter by daypart profile (morning, prime, late_night, etc.)"),
    genre: str | None = Query(None, description="Filter by genre"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    List assets available for scheduling, with optional filters.

    This endpoint powers the content browser sidebar in the schedule builder UI.
    """
    query = (
        db.query(Asset, AssetEditorial)
        .outerjoin(AssetEditorial, Asset.uuid == AssetEditorial.asset_uuid)
        .filter(Asset.state == "ready")
        .filter(Asset.approved_for_broadcast == True)  # noqa: E712
        .filter(Asset.is_deleted == False)  # noqa: E712
    )

    # Apply filters based on editorial metadata
    if content_class or daypart_profile or genre:
        # Filter using JSONB payload fields
        if content_class:
            query = query.filter(
                AssetEditorial.payload["content_class"].astext == content_class
            )
        if daypart_profile:
            query = query.filter(
                AssetEditorial.payload["daypart_profile"].astext == daypart_profile
            )
        if genre:
            # Genre is stored as an array in JSONB
            query = query.filter(
                AssetEditorial.payload["genres"].contains([genre])
            )

    # Apply pagination
    total = query.count()
    assets = query.order_by(Asset.discovered_at.desc()).offset(offset).limit(limit).all()

    # Format response
    items = []
    for asset, editorial in assets:
        payload = editorial.payload if editorial else {}
        items.append({
            "uuid": str(asset.uuid),
            "uri": asset.uri,
            "duration_ms": asset.duration_ms,
            "content_class": payload.get("content_class"),
            "daypart_profile": payload.get("daypart_profile"),
            "genres": payload.get("genres", []),
            "title": payload.get("title") or payload.get("series_name"),
            "season": payload.get("season_number"),
            "episode": payload.get("episode_number"),
        })

    return {
        "status": "ok",
        "assets": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ============================================================================
# Schedule Revision Lifecycle Endpoints
# ============================================================================


class RevisionItemCreate(BaseModel):
    """Request model for a schedule revision item."""
    start_time: str = Field(..., description="ISO 8601 datetime with timezone")
    duration_sec: int = Field(..., gt=0, description="Duration in seconds")
    asset_id: str | None = Field(None, description="Asset UUID")
    content_type: str = Field("episode", description="Content type")
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata")


class RevisionCreate(BaseModel):
    """Request model for creating a draft revision."""
    broadcast_day: str = Field(..., description="Broadcast day (YYYY-MM-DD)")
    created_by: str | None = Field(None, description="Operator identifier")
    items: list[RevisionItemCreate] = Field(..., description="Schedule items")


class RevisionItemResponse(BaseModel):
    """Response model for a schedule item."""
    id: str
    start_time: str
    duration_sec: int
    asset_id: str | None
    content_type: str
    slot_index: int


class RevisionListResponse(BaseModel):
    """Response model for revision listing (without full items)."""
    id: str
    channel_id: str
    broadcast_day: str
    status: str
    created_at: str | None
    activated_at: str | None
    superseded_at: str | None
    created_by: str | None
    item_count: int


def _revision_to_response(rev) -> dict:
    return {
        "id": str(rev.id),
        "channel_id": str(rev.channel_id),
        "broadcast_day": str(rev.broadcast_day),
        "status": rev.status,
        "created_at": rev.created_at.isoformat() if rev.created_at else None,
        "activated_at": rev.activated_at.isoformat() if rev.activated_at else None,
        "superseded_at": rev.superseded_at.isoformat() if rev.superseded_at else None,
        "created_by": rev.created_by,
        "items": [
            {
                "id": str(item.id),
                "start_time": item.start_time.isoformat() if item.start_time else None,
                "duration_sec": item.duration_sec,
                "asset_id": str(item.asset_id) if item.asset_id else None,
                "content_type": item.content_type,
                "slot_index": item.slot_index,
            }
            for item in rev.items
        ],
    }


def _revision_to_list_response(rev) -> dict:
    return {
        "id": str(rev.id),
        "channel_id": str(rev.channel_id),
        "broadcast_day": str(rev.broadcast_day),
        "status": rev.status,
        "created_at": rev.created_at.isoformat() if rev.created_at else None,
        "activated_at": rev.activated_at.isoformat() if rev.activated_at else None,
        "superseded_at": rev.superseded_at.isoformat() if rev.superseded_at else None,
        "created_by": rev.created_by,
        "item_count": len(rev.items),
    }


@router.post(
    "/channels/{channel_id}/revisions",
    status_code=201,
    tags=["revisions"],
)
def create_revision_endpoint(
    channel_id: str,
    body: RevisionCreate,
    db: Session = Depends(get_db),
):
    """Create a draft schedule revision with items."""
    try:
        channel_uuid = uuid_module.UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id format")

    try:
        rev = create_draft_revision(
            db,
            channel_id=channel_uuid,
            broadcast_day=date.fromisoformat(body.broadcast_day),
            items=[item.model_dump() for item in body.items],
            created_by=body.created_by,
        )
        db.commit()
        return _revision_to_response(rev)
    except ChannelNotFoundError:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
    except RevisionEmptyError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get(
    "/channels/{channel_id}/revisions",
    tags=["revisions"],
)
def list_revisions_endpoint(
    channel_id: str,
    broadcast_day: str | None = Query(None, description="Filter by broadcast day (YYYY-MM-DD)"),
    status: str | None = Query(None, description="Filter by status"),
    db: Session = Depends(get_db),
):
    """List schedule revisions for a channel."""
    try:
        channel_uuid = uuid_module.UUID(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel_id format")

    try:
        bd = date.fromisoformat(broadcast_day) if broadcast_day else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid broadcast_day format")

    try:
        revisions = list_revisions(
            db,
            channel_id=channel_uuid,
            broadcast_day=bd,
            status=status,
        )
        return [_revision_to_list_response(rev) for rev in revisions]
    except ChannelNotFoundError:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")


@router.get(
    "/revisions/{revision_id}",
    tags=["revisions"],
)
def get_revision_endpoint(
    revision_id: str,
    db: Session = Depends(get_db),
):
    """Get a single schedule revision with items."""
    try:
        rev_uuid = uuid_module.UUID(revision_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid revision_id format")

    try:
        rev = get_revision(db, revision_id=rev_uuid)
        return _revision_to_response(rev)
    except RevisionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Revision {revision_id} not found")


@router.post(
    "/revisions/{revision_id}/publish",
    tags=["revisions"],
)
def publish_revision_endpoint(
    revision_id: str,
    db: Session = Depends(get_db),
    clock: AuthoritativeClock = Depends(get_clock),
):
    """Publish a draft revision (draft -> active)."""
    try:
        rev_uuid = uuid_module.UUID(revision_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid revision_id format")

    try:
        rev = publish_revision(db, revision_id=rev_uuid, now=clock.now_utc())
        db.commit()
        return {
            "id": str(rev.id),
            "channel_id": str(rev.channel_id),
            "broadcast_day": str(rev.broadcast_day),
            "status": rev.status,
            "activated_at": rev.activated_at.isoformat() if rev.activated_at else None,
            "superseded_revision_id": None,
        }
    except RevisionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Revision {revision_id} not found")
    except RevisionNotDraftError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RevisionEmptyError as e:
        raise HTTPException(status_code=422, detail=str(e))
