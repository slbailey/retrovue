"""
DEPRECATED — Console asset tagging workflow (RETA-195).

This router is deprecated. All new endpoints must go to the domain-named
router in assets.py (/api/assets, /api/tags). These /api/console/* routes
are kept temporarily as backward-compatibility aliases and will be removed
once all clients have migrated.

See: RETA-209 Phase 3.5

Invariant: INV-API-NO-BUSINESS-LOGIC-001
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from ...domain.entities import Asset, AssetTag
from ...domain.tag_normalization import canonicalize_tag
from ...infra.uow import session as get_session
from ...runtime.clock import AuthoritativeClock
from ._clock import get_clock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/console", tags=["console-deprecated"], deprecated=True)


# ---------------------------------------------------------------------------
# Deprecation logging — fires on every /api/console/* request
# ---------------------------------------------------------------------------

def _log_deprecation(request: Request):
    logger.warning("DEPRECATED API: /api/console/* called — use /api/assets or /api/tags instead (path=%s)", request.url.path)


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
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _log_deprecation(request)
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
    request: Request,
    asset_uuid: str,
    body: AssetPatchRequest,
    db: Session = Depends(get_db),
    clock: AuthoritativeClock = Depends(get_clock),
) -> dict[str, Any]:
    """Update asset fields for Console review workflow."""
    _log_deprecation(request)
    asset = _resolve_asset(db, asset_uuid)

    if body.approved_for_broadcast is not None:
        asset.approved_for_broadcast = body.approved_for_broadcast

    if body.state is not None:
        asset.state = body.state

    asset.updated_at = clock.now_utc()
    db.add(asset)
    db.flush()

    tags = _get_asset_tags(db, asset.uuid)
    return _serialize_asset(asset, tags)


# ---------------------------------------------------------------------------
# POST /api/console/assets/{asset_uuid}/tags
# ---------------------------------------------------------------------------

@router.post("/assets/{asset_uuid}/tags")
def add_tags(
    request: Request,
    asset_uuid: str,
    body: TagsRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Add tags to an asset. Tags are normalized per INV-ASSET-TAG-PERSISTENCE-001."""
    from retrovue.catalog import asset_tag_service

    _log_deprecation(request)
    asset = _resolve_asset(db, asset_uuid)
    # Phase 9 Step 5: writes route through AssetTagService.
    for raw_tag in body.tags:
        asset_tag_service.add_tag(db, asset.uuid, raw_tag, source="operator")
    db.flush()

    tags = _get_asset_tags(db, asset.uuid)
    return {"asset_uuid": str(asset.uuid), "tags": tags}


# ---------------------------------------------------------------------------
# DELETE /api/console/assets/{asset_uuid}/tags/{tag}
# ---------------------------------------------------------------------------

@router.delete("/assets/{asset_uuid}/tags/{tag}")
def remove_tag(
    request: Request,
    asset_uuid: str,
    tag: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove a single tag from an asset. Idempotent — missing tag is not an error.

    Phase 9 Step 5: routes through AssetTagService.
    """
    from retrovue.catalog import asset_tag_service

    _log_deprecation(request)
    asset = _resolve_asset(db, asset_uuid)
    if asset_tag_service.remove_tag(db, asset.uuid, tag):
        db.flush()

    tags = _get_asset_tags(db, asset.uuid)
    return {"asset_uuid": str(asset.uuid), "tags": tags}


# ---------------------------------------------------------------------------
# GET /api/console/tags
# ---------------------------------------------------------------------------

@router.get("/tags")
def list_tags(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all distinct tags across all assets."""
    _log_deprecation(request)
    rows = db.query(distinct(AssetTag.tag)).order_by(AssetTag.tag).all()
    return {"tags": [r[0] for r in rows]}
