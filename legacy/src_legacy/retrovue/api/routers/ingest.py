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

    container_ids: list[str] | None = Field(
        None, description="Optional list of container UUIDs to limit ingest"
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
        limit_ids: list[str] | None = request.container_ids if request else None
        single_id: str | None = (limit_ids[0] if limit_ids and len(limit_ids) == 1 else None)

        # Run the ingest using the new orchestrator
        orchestrator = IngestOrchestrator(db)
        report = orchestrator.run_full_ingest(source_id=source_id, collection_id=single_id)

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


def _container_to_item(container: Any) -> dict[str, Any]:  # noqa: ANN401
    """Build response item with container keys."""
    return {
        "container_id": getattr(container, "container_id", "") or str(getattr(container, "uuid", "")),
        "external_id": container.external_id,
        "name": container.name,
        "enabled": container.sync_enabled,
        "mapping_pairs": container.mapping_pairs,
        "source_type": container.source_type,
        "config": container.config,
    }


@router.get("/sources/{source_id}/containers")
async def get_source_containers(source_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Get containers for a specific source (canonical).

    Returns container-first response. Use this endpoint in new code.
    """
    try:
        from src_legacy.retrovue.content_manager.source_service import SourceService

        source_service = SourceService(db=db)
        containers = source_service.list_enabled_collections(source_id)

        return {
            "source_id": source_id,
            "containers": [_container_to_item(c) for c in containers],
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get source containers: {str(e)}",
        )


@router.put("/sources/{source_id}/containers/{external_id}")
async def update_source_container(
    source_id: str,
    external_id: str,
    sync_enabled: bool | None = None,
    mapping_pairs: list[tuple[str, str]] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Update a source container configuration (canonical).
    """
    return await _update_source_collection_impl(
        source_id, external_id, sync_enabled, mapping_pairs, db
    )


async def _update_source_collection_impl(
    source_id: str,
    external_id: str,
    sync_enabled: bool | None,
    mapping_pairs: list[tuple[str, str]] | None,
    db: Session,
) -> dict[str, Any]:
    """Shared implementation for container/collection update."""
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
                    detail=f"Container {external_id} not found",
                )

        if mapping_pairs is not None:
            success = source_service.update_collection_mapping(
                source_id, external_id, mapping_pairs
            )
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Container {external_id} not found",
                )

        return {"success": True, "message": "Container updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update container: {str(e)}",
        )
