"""
REST API endpoints for catalog operations.

Exposes domain-internal catalog usecases (asset browsing, review, enrichment)
via a JSON API.  All endpoints call the same usecase functions used by the CLI.

Phase 2 of the Asset Domain Alignment Plan (RETA-69).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...infra.uow import session as get_session
from ...usecases.asset_attention import list_assets_needing_attention
from ...usecases.asset_enrich_stale import enrich_stale_assets
from ...usecases.asset_update import get_asset_summary, update_asset_review_status

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


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
# Request models
# ---------------------------------------------------------------------------

class AssetReviewRequest(BaseModel):
    """Request model for updating asset review status."""

    approved: bool | None = Field(None, description="Set approved_for_broadcast")
    state: str | None = Field(None, description="Set asset state (e.g. ready)")


class AssetEnrichRequest(BaseModel):
    """Request model for triggering asset re-enrichment."""

    source_selector: str | None = Field(
        None, description="Source to enrich (UUID, external_id, or name)"
    )
    collection_selector: str | None = Field(
        None, description="Single collection to enrich"
    )
    dry_run: bool = Field(False, description="Preview without persisting")
    max_assets: int | None = Field(None, description="Limit number of assets to enrich")


# ---------------------------------------------------------------------------
# Asset browsing
# ---------------------------------------------------------------------------

@router.get("/assets")
def list_assets(
    collection_uuid: str | None = Query(None, description="Filter by collection UUID"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List assets needing operator attention.

    Returns assets where state == 'enriching' OR approved_for_broadcast == False.
    """
    assets = list_assets_needing_attention(
        db, collection_uuid=collection_uuid, limit=limit
    )
    return {"assets": assets, "count": len(assets)}


@router.get("/assets/{asset_uuid}")
def get_asset(
    asset_uuid: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a single asset summary by UUID."""
    try:
        return get_asset_summary(db, asset_uuid=asset_uuid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Asset review
# ---------------------------------------------------------------------------

@router.post("/assets/{asset_uuid}/review")
def review_asset(
    asset_uuid: str,
    body: AssetReviewRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update asset review status (approval and/or state transition).

    Respects INV-ASSET-APPROVAL-OPERATOR-ONLY-001 and
    INV-ASSET-STATE-MACHINE-001 constraints.
    """
    try:
        return update_asset_review_status(
            db, asset_uuid=asset_uuid, approved=body.approved, state=body.state
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Asset enrichment
# ---------------------------------------------------------------------------

@router.post("/assets/enrich")
def enrich_assets(
    body: AssetEnrichRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger re-enrichment of stale assets.

    Exactly one of source_selector or collection_selector must be provided.
    """
    if not body.source_selector and not body.collection_selector:
        raise HTTPException(
            status_code=400,
            detail="Provide source_selector or collection_selector",
        )
    if body.source_selector and body.collection_selector:
        raise HTTPException(
            status_code=400,
            detail="Provide only one of source_selector or collection_selector",
        )

    try:
        result = enrich_stale_assets(
            db,
            source_selector=body.source_selector,
            collection_selector=body.collection_selector,
            dry_run=body.dry_run,
            max_assets=body.max_assets,
        )
        return result.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
