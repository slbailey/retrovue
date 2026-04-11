"""
REST API endpoints for Console asset tagging workflow (RETA-195).

Thin HTTP layer — delegates to domain entities and tag normalization.
No business logic here.

Invariant: INV-API-NO-BUSINESS-LOGIC-001
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from ...domain.entities import Asset, AssetTag
from ...domain.tag_normalization import canonicalize_tag
from ...infra.uow import session as get_session

router = APIRouter(prefix="/api/console", tags=["console"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def get_db():
    """Get database session for dependency injection."""
    db = get_session()
    try:
        with db as session:
            yield session
    finally:
        pass


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class AssetPatchRequest(BaseModel):
    """Fields updatable via PATCH on an asset."""

    approved_for_broadcast: bool | None = Field(None)
    state: str | None = Field(None)


class TagsRequest(BaseModel):
    """Request model for adding tags to an asset."""

    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_asset(asset: Asset, tags: list[str] | None = None) -> dict[str, Any]:
    return {
        "uuid": str(asset.uuid),
        "container_id": str(asset.container_id),
        "uri": asset.uri,
        "canonical_uri": asset.canonical_uri,
        "state": asset.state,
        "approved_for_broadcast": bool(asset.approved_for_broadcast),
        "duration_ms": asset.duration_ms,
        "tags": tags if tags is not None else [],
    }


def _get_asset_tags(db: Session, asset_uuid) -> list[str]:
    rows = (
        db.query(AssetTag.tag)
        .filter(AssetTag.asset_uuid == asset_uuid)
        .order_by(AssetTag.tag)
        .all()
    )
    return [r[0] for r in rows]


def _resolve_asset(db: Session, asset_uuid: str) -> Asset:
    import uuid as _uuid

    try:
        uid = _uuid.UUID(asset_uuid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Asset not found") from exc

    asset = db.get(Asset, uid)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


# ---------------------------------------------------------------------------
# GET /api/console/assets
# ---------------------------------------------------------------------------

@router.get("/assets")
def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List assets with their tags for the Console UI (paginated)."""
    base_query = db.query(Asset).filter(Asset.is_deleted.is_(False))

    total = base_query.count()

    offset = (page - 1) * page_size
    assets = (
        base_query
        .order_by(Asset.updated_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Batch-load tags
    asset_uuids = [a.uuid for a in assets]
    tag_rows = (
        db.query(AssetTag.asset_uuid, AssetTag.tag)
        .filter(AssetTag.asset_uuid.in_(asset_uuids))
        .all()
    ) if asset_uuids else []

    tags_by_uuid: dict[str, list[str]] = {}
    for t_uuid, t_tag in tag_rows:
        tags_by_uuid.setdefault(str(t_uuid), []).append(t_tag)

    result = [
        _serialize_asset(a, sorted(tags_by_uuid.get(str(a.uuid), [])))
        for a in assets
    ]
    return {
        "assets": result,
        "count": len(result),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# PATCH /api/console/assets/{asset_uuid}
# ---------------------------------------------------------------------------

@router.patch("/assets/{asset_uuid}")
def patch_asset(
    asset_uuid: str,
    body: AssetPatchRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update asset fields for Console review workflow."""
    asset = _resolve_asset(db, asset_uuid)

    if body.approved_for_broadcast is not None:
        asset.approved_for_broadcast = body.approved_for_broadcast

    if body.state is not None:
        asset.state = body.state

    asset.updated_at = datetime.now(UTC)
    db.add(asset)
    db.flush()

    tags = _get_asset_tags(db, asset.uuid)
    return _serialize_asset(asset, tags)


# ---------------------------------------------------------------------------
# POST /api/console/assets/{asset_uuid}/tags
# ---------------------------------------------------------------------------

@router.post("/assets/{asset_uuid}/tags")
def add_tags(
    asset_uuid: str,
    body: TagsRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add tags to an asset. Tags are normalized per INV-ASSET-TAG-PERSISTENCE-001."""
    asset = _resolve_asset(db, asset_uuid)

    existing = set(_get_asset_tags(db, asset.uuid))

    for raw_tag in body.tags:
        normalized = canonicalize_tag(raw_tag)
        if not normalized or normalized in existing:
            continue
        db.add(AssetTag(
            asset_uuid=asset.uuid,
            tag=normalized,
            source="operator",
        ))
        existing.add(normalized)

    db.flush()

    tags = _get_asset_tags(db, asset.uuid)
    return {"asset_uuid": str(asset.uuid), "tags": tags}


# ---------------------------------------------------------------------------
# DELETE /api/console/assets/{asset_uuid}/tags/{tag}
# ---------------------------------------------------------------------------

@router.delete("/assets/{asset_uuid}/tags/{tag}")
def remove_tag(
    asset_uuid: str,
    tag: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove a single tag from an asset. Idempotent — missing tag is not an error."""
    asset = _resolve_asset(db, asset_uuid)

    existing = (
        db.query(AssetTag)
        .filter(AssetTag.asset_uuid == asset.uuid, AssetTag.tag == tag)
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    tags = _get_asset_tags(db, asset.uuid)
    return {"asset_uuid": str(asset.uuid), "tags": tags}


# ---------------------------------------------------------------------------
# GET /api/console/tags
# ---------------------------------------------------------------------------

@router.get("/tags")
def list_tags(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all distinct tags across all assets."""
    rows = db.query(distinct(AssetTag.tag)).order_by(AssetTag.tag).all()
    return {"tags": [r[0] for r in rows]}
