"""
Web pages for Retrovue admin GUI.

This module provides server-rendered pages with HTMX interactions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from src_legacy.retrovue.content_manager.ingest_orchestrator import IngestOrchestrator
from src_legacy.retrovue.content_manager.library_service import LibraryService
from src_legacy.retrovue.content_manager.source_service import SourceService

from ...domain.entities import ReviewQueue, ReviewStatus
from ...infra.uow import get_db

# Setup templates
templates = Jinja2Templates(directory="src/retrovue/api/web/templates")

# Create router
router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard with overview tiles."""
    from ...domain.entities import Asset, Collection, Source

    # Get DB-backed counts
    total_assets = db.query(Asset).count()
    canonical_assets = db.query(Asset).filter(Asset.canonical.is_(True)).count()
    pending_assets = db.query(Asset).filter(Asset.canonical.is_(False)).count()
    total_sources = db.query(Source).count()
    enabled_collections = db.query(Collection).filter(Collection.sync_enabled.is_(True)).count()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": {
                "total_assets": total_assets,
                "canonical_assets": canonical_assets,
                "pending_assets": pending_assets,
                "total_sources": total_sources,
                "enabled_collections": enabled_collections,
            },
        },
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources_list(request: Request, db: Session = Depends(get_db)):
    """List content sources."""
    from ...domain.entities import Source

    # Get all sources from database
    db_sources = db.query(Source).all()

    # Convert to template format
    sources = []
    for source in db_sources:
        sources.append(
            {
                "id": source.external_id,
                "kind": source.type,
                "name": source.name,
                "status": "active",  # Default status since Source model doesn't have status
                "base_url": source.config.get("base_url", "") if source.config else "",
            }
        )

    # Add default filesystem source if no sources exist
    if not sources:
        sources.append(
            {
                "id": "filesystem-1",
                "kind": "filesystem",
                "name": "Local Filesystem",
                "status": "active",
                "base_url": None,
            }
        )

    return templates.TemplateResponse("sources_list.html", {"request": request, "sources": sources})


@router.get("/sources/new", response_class=HTMLResponse)
async def new_source_form(request: Request):
    """Form to add a new Plex server."""
    return templates.TemplateResponse("source_new.html", {"request": request})


@router.post("/sources")
async def create_source(
    request: Request,
    name: str = Form(...),
    base_url: str = Form(...),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    """Create a new Plex source."""
    # Use the source service to create the source
    source_service = SourceService(db)
    source_service.create_plex_source(name, base_url, token)

    return RedirectResponse(url="/sources", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/sources/{source_id}", response_class=HTMLResponse)
async def source_detail(request: Request, source_id: str, db: Session = Depends(get_db)):
    """Source detail page with actions."""
    from ...domain.entities import Source

    # Get source from database
    source_entity = db.query(Source).filter(Source.external_id == source_id).first()

    if not source_entity:
        # Fallback for filesystem source
        if source_id == "filesystem-1":
            source = {
                "id": source_id,
                "kind": "filesystem",
                "name": "Local Filesystem",
                "base_url": None,
                "status": "active",
            }
        else:
            raise HTTPException(status_code=404, detail="Source not found")
    else:
        source = {
            "id": source_entity.external_id,
            "kind": source_entity.type,
            "name": source_entity.name,
            "base_url": source_entity.config.get("base_url", "") if source_entity.config else "",
            "status": "active",  # Default status since Source model doesn't have status
        }

    return templates.TemplateResponse("source_detail.html", {"request": request, "source": source})


@router.post("/sources/{source_id}/discover")
async def discover_libraries(request: Request, source_id: str, db: Session = Depends(get_db)):
    """Discover Plex libraries."""
    try:
        # Use source service to discover collections
        source_service = SourceService(db)
        collections_dto = source_service.discover_collections(source_id)

        # Convert to template format
        collections = []
        for collection in collections_dto:
            collections.append(
                {
                    "external_id": collection.external_id,
                    "name": collection.name,
                    "enabled": collection.sync_enabled,
                    "mapping_pairs": collection.mapping_pairs,
                    "source_type": collection.source_type,
                    "config": collection.config,
                }
            )

        return templates.TemplateResponse(
            "collections_table.html",
            {"request": request, "source_id": source_id, "collections": collections},
        )
    except Exception as e:
        # Return error message
        return templates.TemplateResponse(
            "collections_table.html",
            {
                "request": request,
                "source_id": source_id,
                "collections": [],
                "error": f"Failed to discover libraries: {str(e)}",
            },
        )


@router.get("/sources/{source_id}/collections", response_class=HTMLResponse)
async def source_collections(request: Request, source_id: str, db: Session = Depends(get_db)):
    """Collections table for a source."""
    try:
        # Use source service to get collections
        source_service = SourceService(db)
        collections_dto = source_service.list_enabled_collections(source_id)

        # Convert to template format
        collections = []
        for collection in collections_dto:
            collections.append(
                {
                    "external_id": collection.external_id,
                    "name": collection.name,
                    "enabled": collection.sync_enabled,
                    "mapping_pairs": collection.mapping_pairs,
                    "source_type": collection.source_type,
                    "config": collection.config,
                }
            )

        return templates.TemplateResponse(
            "collections_table.html",
            {"request": request, "source_id": source_id, "collections": collections},
        )

    except Exception as e:
        return templates.TemplateResponse(
            "collections_table.html",
            {
                "request": request,
                "source_id": source_id,
                "collections": [],
                "error": f"Failed to load collections: {str(e)}",
            },
        )


@router.post("/ingest/run")
async def run_ingest(
    request: Request,
    source: str = Form(...),
    source_id: str = Form(...),
    library_ids: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """Run ingest pipeline."""
    import json

    try:
        json.loads(library_ids) if library_ids else []
    except json.JSONDecodeError:
        pass

    # Run ingest using the new orchestrator
    orchestrator = IngestOrchestrator(db)
    report = orchestrator.run_full_ingest(source_id=source_id)
    result = report.to_dict()

    return templates.TemplateResponse("ingest_summary.html", {"request": request, "result": result})


@router.get("/assets", response_class=HTMLResponse)
async def assets_list(request: Request, search: str = "", db: Session = Depends(get_db)):
    """List canonical assets."""
    # Use library service to get canonical assets
    library_service = LibraryService(db)
    assets = library_service.list_canonical_assets(query=search if search else None)

    # Convert to DTOs for consistent serialization
    from ...api.schemas import AssetSummary

    asset_dtos = [AssetSummary.from_orm(asset) for asset in assets]

    return templates.TemplateResponse(
        "assets_list.html", {"request": request, "assets": asset_dtos, "search": search}
    )


@router.post("/play")
async def play_asset(request: Request, asset_id: str = Form(...), db: Session = Depends(get_db)):
    """Play an asset by launching it with the OS."""
    library_service = LibraryService(db)

    # Get asset
    session = library_service._get_session()
    from ...domain.entities import Asset

    asset = session.get(Asset, uuid.UUID(asset_id))

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Launch file with OS
    import os
    import platform
    import subprocess

    try:
        if platform.system() == "Windows":
            # Windows: use start command
            subprocess.run(["cmd", "/c", "start", "", asset.uri], check=True)
            message = f"Launched: {os.path.basename(asset.uri)}"
        elif platform.system() == "Darwin":
            # macOS: use open command
            subprocess.run(["open", asset.uri], check=True)
            message = f"Launched: {os.path.basename(asset.uri)}"
        elif platform.system() == "Linux":
            # Linux: use xdg-open
            subprocess.run(["xdg-open", asset.uri], check=True)
            message = f"Launched: {os.path.basename(asset.uri)}"
        else:
            message = f"File path: {asset.uri}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        message = f"Could not launch file. Path: {asset.uri}"

    return templates.TemplateResponse(
        "playback_result.html", {"request": request, "message": message, "asset_id": asset_id}
    )


@router.put("/sources/{source_id}/collections/{external_id}")
async def update_collection(
    request: Request, source_id: str, external_id: str, db: Session = Depends(get_db)
):
    """Update a collection (enable/disable, mapping pairs)."""
    try:
        # Parse form data
        form_data = await request.form()
        sync_enabled = form_data.get("sync_enabled") == "true"
        mapping_pairs = form_data.get("mapping_pairs", "[]")

        # Parse mapping pairs if provided
        mapping_pairs_list = []
        if mapping_pairs:
            try:
                import json

                mapping_pairs_list = json.loads(mapping_pairs)
            except json.JSONDecodeError:
                pass

        # Use source service to update collection
        source_service = SourceService(db)

        # Update sync enabled status
        success = source_service.update_collection_sync_enabled(
            source_id, external_id, sync_enabled
        )
        if not success:
            raise Exception(f"Failed to update collection {external_id}")

        # Update mapping pairs
        if mapping_pairs_list:
            success = source_service.update_collection_mapping(
                source_id, external_id, mapping_pairs_list
            )
            if not success:
                raise Exception(f"Failed to update mapping pairs for collection {external_id}")

        # Get updated collection
        collection_dto = source_service.get_collection(source_id, external_id)
        if not collection_dto:
            raise Exception(f"Collection {external_id} not found after update")

        # Return updated row HTML
        return templates.TemplateResponse(
            "collection_row.html",
            {
                "request": request,
                "source_id": source_id,
                "collection": {
                    "external_id": collection_dto.external_id,
                    "name": collection_dto.name,
                    "sync_enabled": collection_dto.sync_enabled,
                    "mapping_pairs": collection_dto.mapping_pairs,
                    "source_type": collection_dto.source_type,
                    "config": collection_dto.config,
                },
            },
        )

    except Exception as e:
        # Return error row
        return f'<tr><td colspan="7" class="px-6 py-4 text-red-600">Error: {str(e)}</td></tr>'


@router.get("/review", response_class=HTMLResponse)
async def review_list(request: Request, db: Session = Depends(get_db)):
    """List pending review items."""
    library_service = LibraryService(db)
    reviews = library_service.list_review_queue()

    # Convert to template format
    review_items = []
    for review in reviews:
        asset = review.asset
        review_items.append(
            {
                "id": str(review.id),
                "asset_id": str(asset.id),
                "uri": asset.uri,
                "size": asset.size,
                "reason": review.reason,
                "confidence": review.confidence,
                "created_at": review.created_at,
                "raw_labels": getattr(asset, "raw_labels", {})
                if hasattr(asset, "raw_labels")
                else {},
            }
        )

    return templates.TemplateResponse(
        "review_list.html", {"request": request, "reviews": review_items}
    )


@router.get("/review/{review_id}", response_class=HTMLResponse)
async def review_detail(request: Request, review_id: str, db: Session = Depends(get_db)):
    """Show review item details with resolution form."""

    # Get the review item
    review = db.get(ReviewQueue, uuid.UUID(review_id))
    if not review:
        raise HTTPException(status_code=404, detail="Review item not found")

    # Get the asset
    asset = review.asset

    # Extract raw labels for display
    raw_labels = {}
    if hasattr(asset, "raw_labels") and asset.raw_labels:
        raw_labels = asset.raw_labels

    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            "review": {
                "id": str(review.id),
                "reason": review.reason,
                "confidence": review.confidence,
                "created_at": review.created_at,
            },
            "asset": {
                "id": str(asset.id),
                "uri": asset.uri,
                "size": asset.size,
                "hash_sha256": asset.hash_sha256,
                "canonical": asset.canonical,
            },
            "raw_labels": raw_labels,
        },
    )


@router.post("/review/{review_id}/resolve")
async def resolve_review(
    request: Request,
    review_id: str,
    title: str = Form(...),
    episode_title: str = Form(""),
    season: int = Form(None),
    episode: int = Form(None),
    year: int = Form(None),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Resolve a review item by creating/updating episode and linking asset."""
    library_service = LibraryService(db)

    try:
        # For now, we'll create a simple resolution by marking the asset as canonical
        # In a full implementation, this would create/update episodes and link them

        # Get the review
        review = db.get(ReviewQueue, uuid.UUID(review_id))
        if not review:
            raise HTTPException(status_code=404, detail="Review item not found")

        # Mark the asset as canonical
        library_service.mark_asset_canonical(review.asset_id, True)

        # Update the review status
        review.status = ReviewStatus.RESOLVED
        review.resolved_at = datetime.utcnow()

        # Add notes if provided
        if notes:
            # Note: ReviewQueue doesn't have a notes field in the current schema
            # This would need to be added to the entity if notes are required
            pass

        db.commit()

        return RedirectResponse(url="/review", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to resolve review: {str(e)}")
