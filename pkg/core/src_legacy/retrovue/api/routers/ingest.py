"""
Ingest API endpoints.

This module provides REST API endpoints for running the ingest pipeline.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src_legacy.retrovue.content_manager.ingest_orchestrator import IngestOrchestrator

from ...infra.uow import get_db

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    """Request body for ingest operations."""

    library_ids: list[str] | None = Field(
        None, description="Optional list of library IDs to override enabled collections"
    )
    enrichers: list[str] | None = Field(
        None, description="Optional list of enricher names to apply"
    )


class IngestResponse(BaseModel):
    """Response for ingest operations."""

    success: bool = Field(True, description="Whether the operation was successful")
    discovered: int = Field(..., description="Number of items discovered")
    registered: int = Field(..., description="Number of items registered")
    enriched: int = Field(..., description="Number of items enriched")
    canonicalized: int = Field(..., description="Number of items canonicalized")
    queued_for_review: int = Field(..., description="Number of items queued for review")
    error: str | None = Field(None, description="Error message if operation failed")


@router.post("/run", response_model=IngestResponse)
async def run_ingest(
    source: str = Query(..., description="Source type (plex, filesystem, etc.)"),
    source_id: str | None = Query(None, description="Optional source ID"),
    request: IngestRequest | None = None,
    db: Session = Depends(get_db),
) -> IngestResponse:
    """
    Run the ingest pipeline for a specific source.

    Args:
        source: Source type to ingest from
        source_id: Optional source ID
        request: Optional request body with library IDs and enrichers

    Returns:
        Ingest response with summary counts
    """
    try:
        # Extract parameters from request body

        if request:
            pass

        # Run the ingest using the new orchestrator
        orchestrator = IngestOrchestrator(db)
        report = orchestrator.run_full_ingest(source_id=source_id)

        # Return success response
        return IngestResponse(
            success=True,
            discovered=report.discovered,
            registered=report.registered,
            enriched=report.enriched,
            canonicalized=report.canonicalized,
            queued_for_review=report.queued_for_review,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run ingest pipeline: {str(e)}",
        )


@router.get("/sources/{source_id}/collections")
async def get_source_collections(source_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Get collections for a specific source.

    Args:
        source_id: Source identifier

    Returns:
        Dictionary with collections and mapping configuration
    """
    try:
        from src_legacy.retrovue.content_manager.source_service import SourceService

        source_service = SourceService(db=db)
        collections = source_service.list_enabled_collections(source_id)

        return {
            "source_id": source_id,
            "collections": [
                {
                    "external_id": collection.external_id,
                    "name": collection.name,
                    "enabled": collection.sync_enabled,
                    "mapping_pairs": collection.mapping_pairs,
                    "source_type": collection.source_type,
                    "config": collection.config,
                }
                for collection in collections
            ],
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get source collections: {str(e)}",
        )


@router.put("/sources/{source_id}/collections/{external_id}")
async def update_source_collection(
    source_id: str,
    external_id: str,
    sync_enabled: bool | None = None,
    mapping_pairs: list[tuple[str, str]] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Update a source collection configuration.

    Args:
        source_id: Source identifier
        external_id: Collection external ID
        sync_enabled: New sync enabled status
        mapping_pairs: New mapping pairs

    Returns:
        Success status
    """
    try:
        from src_legacy.retrovue.content_manager.source_service import SourceService

        source_service = SourceService(db=db)

        if sync_enabled is not None:
            success = source_service.update_collection_sync_enabled(
                source_id, external_id, sync_enabled
            )
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Collection {external_id} not found",
                )

        if mapping_pairs is not None:
            success = source_service.update_collection_mapping(
                source_id, external_id, mapping_pairs
            )
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Collection {external_id} not found",
                )

        return {"success": True, "message": "Collection updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update collection: {str(e)}",
        )
