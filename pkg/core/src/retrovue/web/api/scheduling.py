"""
REST API endpoints for schedule management.

Provides a frontend-agnostic JSON API that can be consumed by HTMX templates,
React/Vue SPAs, or any other HTTP client.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...domain.entities import Asset, AssetEditorial, Channel, SchedulePlan, Zone
from ...infra.uow import session as get_session
from ...usecases import plan_add, plan_delete, plan_list, plan_update
from ...usecases import zone_add, zone_delete, zone_list, zone_update
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


class PlanCreate(BaseModel):
    """Request model for creating a schedule plan."""
    name: str = Field(..., description="Plan name (unique within channel)")
    description: str | None = Field(None, description="Human-readable description")
    cron_expression: str | None = Field(None, description="Cron expression (hour/min ignored)")
    start_date: str | None = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="End date (YYYY-MM-DD)")
    priority: int | None = Field(0, ge=0, description="Priority (higher = higher priority)")
    is_active: bool = Field(True, description="Active status")


class PlanUpdate(BaseModel):
    """Request model for updating a schedule plan."""
    name: str | None = Field(None, description="New plan name")
    description: str | None = Field(None, description="New description")
    cron_expression: str | None = Field(None, description="New cron expression")
    start_date: str | None = Field(None, description="New start date (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="New end date (YYYY-MM-DD)")
    priority: int | None = Field(None, ge=0, description="New priority")
    is_active: bool | None = Field(None, description="New active status")
    clear_description: bool = Field(False, description="Clear description")
    clear_cron: bool = Field(False, description="Clear cron expression")
    clear_start_date: bool = Field(False, description="Clear start date")
    clear_end_date: bool = Field(False, description="Clear end date")


class PlanResponse(BaseModel):
    """Response model for schedule plan."""
    id: str
    channel_id: str
    name: str
    description: str | None
    cron_expression: str | None
    start_date: str | None
    end_date: str | None
    priority: int
    is_active: bool
    created_at: str | None
    updated_at: str | None


class ZoneCreate(BaseModel):
    """Request model for creating a zone."""
    name: str = Field(..., description="Zone name (e.g., 'Morning Cartoons')")
    start_time: str = Field(..., description="Start time in HH:MM format")
    end_time: str = Field(..., description="End time in HH:MM format (use 24:00 for end of day)")
    schedulable_assets: list[str] | None = Field(None, description="List of asset/program UUIDs")
    day_filters: list[str] | None = Field(None, description="Day filters (MON,TUE,...)")
    enabled: bool = Field(True, description="Active status")
    effective_start: str | None = Field(None, description="Start date (YYYY-MM-DD)")
    effective_end: str | None = Field(None, description="End date (YYYY-MM-DD)")
    dst_policy: str | None = Field(None, description="DST policy")


class ZoneUpdate(BaseModel):
    """Request model for updating a zone."""
    name: str | None = Field(None, description="New zone name")
    start_time: str | None = Field(None, description="New start time")
    end_time: str | None = Field(None, description="New end time")
    schedulable_assets: list[str] | None = Field(None, description="New asset list")
    day_filters: list[str] | None = Field(None, description="New day filters")
    clear_day_filters: bool = Field(False, description="Clear day filters")
    enabled: bool | None = Field(None, description="New active status")
    effective_start: str | None = Field(None, description="New start date")
    effective_end: str | None = Field(None, description="New end date")
    clear_effective_start: bool = Field(False, description="Clear start date")
    clear_effective_end: bool = Field(False, description="Clear end date")
    dst_policy: str | None = Field(None, description="New DST policy")
    clear_dst_policy: bool = Field(False, description="Clear DST policy")


class ZoneResponse(BaseModel):
    """Response model for zone."""
    id: str
    plan_id: str
    name: str
    start_time: str
    end_time: str
    schedulable_assets: list[Any]
    day_filters: list[str] | None
    enabled: bool
    effective_start: str | None
    effective_end: str | None
    dst_policy: str | None
    created_at: str | None
    updated_at: str | None


class AssetSummary(BaseModel):
    """Summary model for assets in content browser."""
    uuid: str
    uri: str
    duration_ms: int | None
    content_class: str | None
    daypart_profile: str | None
    genres: list[str] | None
    title: str | None


class SchedulePreviewSlot(BaseModel):
    """A single time slot in the schedule preview."""
    start_time: str
    end_time: str
    zone_id: str | None
    zone_name: str | None
    content: list[dict[str, Any]]


class SchedulePreviewResponse(BaseModel):
    """Response model for schedule preview."""
    date: str
    channel_id: str
    plan_id: str
    slots: list[SchedulePreviewSlot]
    warnings: list[str]


# ============================================================================
# Channel Plans Endpoints
# ============================================================================


@router.get("/channels/{channel_id}/plans")
async def list_channel_plans(
    channel_id: str,
    active_only: bool = Query(False, description="Filter to active plans only"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all schedule plans for a channel."""
    try:
        result = plan_list.list_plans(db, channel_identifier=channel_id, active_only=active_only)
        return {"status": "ok", "plans": result["plans"], "count": result["count"]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/channels/{channel_id}/plans", status_code=201)
async def create_channel_plan(
    channel_id: str,
    plan: PlanCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new schedule plan for a channel."""
    try:
        result = plan_add.add_plan(
            db,
            channel_identifier=channel_id,
            name=plan.name,
            description=plan.description,
            cron_expression=plan.cron_expression,
            start_date=plan.start_date,
            end_date=plan.end_date,
            priority=plan.priority,
            is_active=plan.is_active,
        )
        return {"status": "ok", "plan": result}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


# ============================================================================
# Plan Endpoints
# ============================================================================


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a schedule plan by ID."""
    from ...usecases.plan_show import show_plan
    try:
        result = show_plan(db, plan_identifier=plan_id)
        return {"status": "ok", "plan": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    plan: PlanUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a schedule plan."""
    try:
        result = plan_update.update_plan(
            db,
            plan_identifier=plan_id,
            name=plan.name,
            description=plan.description,
            cron_expression=plan.cron_expression,
            start_date=plan.start_date,
            end_date=plan.end_date,
            priority=plan.priority,
            is_active=plan.is_active,
            clear_description=plan.clear_description,
            clear_cron=plan.clear_cron,
            clear_start_date=plan.clear_start_date,
            clear_end_date=plan.clear_end_date,
        )
        return {"status": "ok", "plan": result}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a schedule plan."""
    try:
        result = plan_delete.delete_plan(db, plan_identifier=plan_id)
        return {"status": "ok", "deleted": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# Zone Endpoints
# ============================================================================


@router.get("/plans/{plan_id}/zones")
async def list_plan_zones(
    plan_id: str,
    enabled_only: bool = Query(False, description="Filter to enabled zones only"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all zones for a schedule plan."""
    try:
        result = zone_list.list_zones(db, plan_identifier=plan_id, enabled_only=enabled_only)
        return {"status": "ok", "zones": result["zones"], "count": result["count"]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/plans/{plan_id}/zones", status_code=201)
async def create_plan_zone(
    plan_id: str,
    zone: ZoneCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new zone in a schedule plan."""
    try:
        result = zone_add.add_zone(
            db,
            plan_identifier=plan_id,
            name=zone.name,
            start_time=zone.start_time,
            end_time=zone.end_time,
            schedulable_assets=zone.schedulable_assets,
            day_filters=zone.day_filters,
            enabled=zone.enabled,
            effective_start=zone.effective_start,
            effective_end=zone.effective_end,
            dst_policy=zone.dst_policy,
        )
        return {"status": "ok", "zone": result}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


@router.get("/plans/{plan_id}/zones/{zone_id}")
async def get_zone(
    plan_id: str,
    zone_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a zone by ID."""
    try:
        result = zone_list.get_zone(db, zone_identifier=zone_id)
        # Verify zone belongs to the specified plan
        if result["plan_id"] != plan_id:
            raise ValueError(f"Zone '{zone_id}' does not belong to plan '{plan_id}'")
        return {"status": "ok", "zone": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/plans/{plan_id}/zones/{zone_id}")
async def update_zone(
    plan_id: str,
    zone_id: str,
    zone: ZoneUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a zone."""
    try:
        # First verify zone exists and belongs to plan
        existing = zone_list.get_zone(db, zone_identifier=zone_id)
        if existing["plan_id"] != plan_id:
            raise ValueError(f"Zone '{zone_id}' does not belong to plan '{plan_id}'")

        result = zone_update.update_zone(
            db,
            zone_identifier=zone_id,
            name=zone.name,
            start_time=zone.start_time,
            end_time=zone.end_time,
            schedulable_assets=zone.schedulable_assets,
            day_filters=zone.day_filters,
            clear_day_filters=zone.clear_day_filters,
            enabled=zone.enabled,
            effective_start=zone.effective_start,
            effective_end=zone.effective_end,
            clear_effective_start=zone.clear_effective_start,
            clear_effective_end=zone.clear_effective_end,
            dst_policy=zone.dst_policy,
            clear_dst_policy=zone.clear_dst_policy,
        )
        return {"status": "ok", "zone": result}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


@router.delete("/plans/{plan_id}/zones/{zone_id}")
async def delete_zone_endpoint(
    plan_id: str,
    zone_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a zone."""
    try:
        # First verify zone exists and belongs to plan
        existing = zone_list.get_zone(db, zone_identifier=zone_id)
        if existing["plan_id"] != plan_id:
            raise ValueError(f"Zone '{zone_id}' does not belong to plan '{plan_id}'")

        result = zone_delete.delete_zone(db, zone_identifier=zone_id)
        return {"status": "ok", "deleted": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
# Schedule Preview Endpoint
# ============================================================================


@router.post("/plans/{plan_id}/preview")
async def preview_schedule(
    plan_id: str,
    target_date: str = Query(..., description="Date to preview (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Generate a preview of how the schedule will resolve for a specific date.

    Returns a 24-hour timeline showing which zones apply and what content
    would play in each time slot. Includes gap/overlap warnings.
    """
    from datetime import date as date_type, time as time_type

    try:
        target = date_type.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Get the plan
    plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")

    # Get the channel for grid configuration
    channel = db.query(Channel).filter(Channel.id == plan.channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Get all zones for this plan
    zones = (
        db.query(Zone)
        .filter(Zone.plan_id == plan.id)
        .filter(Zone.enabled == True)  # noqa: E712
        .order_by(Zone.start_time)
        .all()
    )

    # Check which zones are active for the target date
    target_day = target.strftime("%a").upper()[:3]  # MON, TUE, etc.

    active_zones = []
    for zone in zones:
        # Check effective date range
        if zone.effective_start and target < zone.effective_start:
            continue
        if zone.effective_end and target > zone.effective_end:
            continue

        # Check day filters
        if zone.day_filters and target_day not in zone.day_filters:
            continue

        active_zones.append(zone)

    # Build timeline slots
    slots = []
    warnings = []

    # End of day sentinel
    end_of_day = time_type(23, 59, 59, 999999)

    def format_time(t: time_type) -> str:
        if t == end_of_day:
            return "24:00:00"
        return t.strftime("%H:%M:%S")

    for zone in active_zones:
        slot = {
            "start_time": format_time(zone.start_time),
            "end_time": format_time(zone.end_time),
            "zone_id": str(zone.id),
            "zone_name": zone.name,
            "content": zone.schedulable_assets or [],
        }
        slots.append(slot)

    # Check for gaps and overlaps using the shared helper
    # (preview keeps warning-only behavior; hard enforcement is in zone_add/zone_update)
    from ...usecases.zone_coverage_check import check_coverage, check_overlap

    pds = getattr(channel, "programming_day_start", time_type(0, 0))
    warnings.extend(check_overlap(active_zones, programming_day_start=pds))
    warnings.extend(check_coverage(active_zones, programming_day_start=pds))

    return {
        "status": "ok",
        "preview": {
            "date": target_date,
            "channel_id": str(plan.channel_id),
            "plan_id": plan_id,
            "slots": slots,
            "warnings": warnings,
        }
    }


# ============================================================================
# Zone Presets Endpoint
# ============================================================================


PRESET_ZONES = {
    "saturday-morning-cartoons": {
        "name": "Saturday Morning Cartoons",
        "start_time": "06:00",
        "end_time": "12:00",
        "day_filters": ["SAT"],
    },
    "weekday-afternoon-comedy": {
        "name": "Weekday Afternoon Comedy",
        "start_time": "15:00",
        "end_time": "18:00",
        "day_filters": ["MON", "TUE", "WED", "THU", "FRI"],
    },
    "prime-time": {
        "name": "Prime Time",
        "start_time": "19:00",
        "end_time": "22:00",
        "day_filters": None,
    },
    "late-night-horror": {
        "name": "Late Night Horror",
        "start_time": "22:00",
        "end_time": "02:00",
        "day_filters": ["FRI", "SAT"],
    },
    "overnight-classics": {
        "name": "Overnight Classics",
        "start_time": "02:00",
        "end_time": "06:00",
        "day_filters": None,
    },
}


@router.get("/presets")
async def list_zone_presets() -> dict[str, Any]:
    """List available zone presets for classic TV dayparts."""
    return {
        "status": "ok",
        "presets": [
            {"id": k, **v}
            for k, v in PRESET_ZONES.items()
        ]
    }


@router.post("/plans/{plan_id}/zones/preset/{preset_id}", status_code=201)
async def create_zone_from_preset(
    plan_id: str,
    preset_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a zone from a classic TV daypart preset."""
    if preset_id not in PRESET_ZONES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset '{preset_id}'. Available: {', '.join(PRESET_ZONES.keys())}"
        )

    preset = PRESET_ZONES[preset_id]
    try:
        result = zone_add.add_zone(
            db,
            plan_identifier=plan_id,
            name=preset["name"],
            start_time=preset["start_time"],
            end_time=preset["end_time"],
            day_filters=preset["day_filters"],
            enabled=True,
        )
        return {"status": "ok", "zone": result, "preset": preset_id}
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


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
):
    """Publish a draft revision (draft → active)."""
    try:
        rev_uuid = uuid_module.UUID(revision_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid revision_id format")

    try:
        rev = publish_revision(db, revision_id=rev_uuid)
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
